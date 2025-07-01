from celery import Task
from celery_app import app
from typing import Dict, Any, Optional
import subprocess
import tempfile
import logging
from pathlib import Path
import json
from datetime import datetime
from ..storage import StorageClient
from ..models import JobStatus, BlastJobResult

logger = logging.getLogger(__name__)


class BlastTask(Task):
    """Base class for BLAST tasks with common functionality"""
    
    def __init__(self):
        self.storage = StorageClient()
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure"""
        job_id = kwargs.get('job_id', task_id)
        self.storage.update_job_status(job_id, JobStatus.FAILED, error=str(exc))
        super().on_failure(exc, task_id, args, kwargs, einfo)


@app.task(base=BlastTask, bind=True, name='bio.tasks.blast.run_blastn')
def run_blastn(
    self,
    job_id: str,
    query_url: str,
    database: str,
    evalue: float = 10.0,
    max_hits: int = 50,
    output_format: str = "json",
    **kwargs
) -> Dict[str, Any]:
    """
    Run BLASTN search as a background job
    
    Args:
        job_id: Unique job identifier
        query_url: S3/MinIO URL to query file
        database: Database name or path
        evalue: E-value threshold
        max_hits: Maximum number of hits
        output_format: Output format
    """
    try:
        # Update job status
        self.storage.update_job_status(job_id, JobStatus.RUNNING)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download query file
            query_path = Path(tmpdir) / "query.fasta"
            self.storage.download_file(query_url, query_path)
            
            # Prepare output path
            output_path = Path(tmpdir) / f"blast_results.{output_format}"
            
            # Format mapping
            format_map = {
                "json": "15",
                "xml": "5",
                "tabular": "6",
                "pairwise": "0"
            }
            
            # Build command
            cmd = [
                "blastn",
                "-query", str(query_path),
                "-db", database,
                "-evalue", str(evalue),
                "-max_target_seqs", str(max_hits),
                "-outfmt", format_map.get(output_format, "6"),
                "-out", str(output_path),
                "-num_threads", "4"  # Use multiple threads
            ]
            
            # Execute BLAST
            logger.info(f"Running BLAST command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=self.time_limit
            )
            
            # Upload results
            result_url = self.storage.upload_file(
                output_path,
                f"results/{job_id}/blast_output.{output_format}"
            )
            
            # Parse results for summary (if JSON)
            summary = {}
            if output_format == "json" and output_path.exists():
                with open(output_path) as f:
                    blast_data = json.load(f)
                    search_info = blast_data.get("BlastOutput2", [{}])[0].get("report", {}).get("results", {}).get("search", {})
                    summary = {
                        "query_title": search_info.get("query_title", ""),
                        "query_len": search_info.get("query_len", 0),
                        "num_hits": len(search_info.get("hits", [])),
                        "database": database
                    }
            
            # Create job result
            job_result = BlastJobResult(
                job_id=job_id,
                status=JobStatus.COMPLETED,
                result_url=result_url,
                summary=summary,
                completed_at=datetime.utcnow(),
                runtime_seconds=(datetime.utcnow() - self.request.started).total_seconds()
            )
            
            # Update job status
            self.storage.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                result=job_result.dict()
            )
            
            return job_result.dict()
            
    except subprocess.TimeoutExpired:
        logger.error(f"BLAST job {job_id} timed out")
        self.storage.update_job_status(job_id, JobStatus.FAILED, error="Job timed out")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"BLAST job {job_id} failed: {e.stderr}")
        self.storage.update_job_status(job_id, JobStatus.FAILED, error=e.stderr)
        raise
    except Exception as e:
        logger.error(f"BLAST job {job_id} failed with unexpected error: {str(e)}")
        self.storage.update_job_status(job_id, JobStatus.FAILED, error=str(e))
        raise


@app.task(base=BlastTask, bind=True, name='bio.tasks.blast.run_blastp')
def run_blastp(
    self,
    job_id: str,
    query_url: str,
    database: str,
    evalue: float = 10.0,
    max_hits: int = 50,
    output_format: str = "json",
    **kwargs
) -> Dict[str, Any]:
    """Run BLASTP search - similar to blastn but for proteins"""
    # Implementation similar to run_blastn but with blastp command
    # Reuse most of the logic from run_blastn
    kwargs['program'] = 'blastp'
    return run_blastn(self, job_id, query_url, database, evalue, max_hits, output_format, **kwargs)


@app.task(base=BlastTask, bind=True, name='bio.tasks.blast.make_blast_db')
def make_blast_db(
    self,
    job_id: str,
    input_url: str,
    database_name: str,
    dbtype: str = "nucl",
    title: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a BLAST database from FASTA file"""
    try:
        self.storage.update_job_status(job_id, JobStatus.RUNNING)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download input file
            input_path = Path(tmpdir) / "input.fasta"
            self.storage.download_file(input_url, input_path)
            
            # Database output path
            db_path = Path(tmpdir) / database_name
            
            # Build command
            cmd = [
                "makeblastdb",
                "-in", str(input_path),
                "-out", str(db_path),
                "-dbtype", dbtype,
                "-title", title or database_name,
                "-parse_seqids"  # Parse sequence IDs for better retrieval
            ]
            
            # Execute makeblastdb
            logger.info(f"Creating BLAST database: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Upload database files
            db_files = list(Path(tmpdir).glob(f"{database_name}.*"))
            db_urls = {}
            
            for db_file in db_files:
                url = self.storage.upload_file(
                    db_file,
                    f"databases/{job_id}/{db_file.name}"
                )
                db_urls[db_file.suffix] = url
            
            job_result = {
                "job_id": job_id,
                "status": JobStatus.COMPLETED,
                "database_name": database_name,
                "database_files": db_urls,
                "dbtype": dbtype,
                "stdout": result.stdout
            }
            
            self.storage.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                result=job_result
            )
            
            return job_result
            
    except Exception as e:
        logger.error(f"Database creation job {job_id} failed: {str(e)}")
        self.storage.update_job_status(job_id, JobStatus.FAILED, error=str(e))
        raise