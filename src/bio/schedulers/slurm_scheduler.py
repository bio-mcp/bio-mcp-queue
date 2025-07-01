import asyncio
import subprocess
import tempfile
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from .base import BaseScheduler, SchedulerType, ResourceRequest
from ..models import JobStatus, JobInfo, JobType
from ..storage import StorageClient

logger = logging.getLogger(__name__)


class SlurmSettings(BaseSettings):
    """Slurm scheduler settings"""
    slurm_partition: Optional[str] = None
    slurm_account: Optional[str] = None
    slurm_qos: Optional[str] = None
    slurm_default_cpus: int = 1
    slurm_default_memory_mb: int = 1024
    slurm_default_walltime_minutes: int = 60
    slurm_work_dir: str = "/tmp/bio-mcp-jobs"
    slurm_modules: List[str] = []
    
    class Config:
        env_prefix = "BIO_SLURM_"


class SlurmJobInfo(BaseModel):
    """Slurm-specific job information"""
    slurm_job_id: str
    job_name: str
    partition: str
    state: str
    submit_time: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    work_dir: str


class SlurmScheduler(BaseScheduler):
    """Slurm-based job scheduler"""
    
    def __init__(self, settings: Optional[SlurmSettings] = None):
        self.settings = settings or SlurmSettings()
        self.storage = StorageClient()
        self._ensure_work_dir()
    
    def _ensure_work_dir(self):
        """Create work directory if it doesn't exist"""
        Path(self.settings.slurm_work_dir).mkdir(parents=True, exist_ok=True)
    
    @property
    def scheduler_type(self) -> SchedulerType:
        return SchedulerType.SLURM
    
    async def is_available(self) -> bool:
        """Check if Slurm is available"""
        try:
            result = await asyncio.create_subprocess_exec(
                "which", "sbatch",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()
            return result.returncode == 0
        except Exception:
            return False
    
    def _create_job_script(
        self,
        job_id: str,
        job_type: str,
        parameters: Dict[str, Any],
        resources: ResourceRequest
    ) -> Path:
        """Create Slurm job script"""
        job_dir = Path(self.settings.slurm_work_dir) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        
        script_path = job_dir / f"{job_id}.sh"
        
        # Build job script content
        script_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name=bio-{job_type}-{job_id[:8]}",
            f"#SBATCH --cpus-per-task={resources.cpus}",
            f"#SBATCH --mem={resources.memory_mb}M",
            f"#SBATCH --time={resources.walltime_minutes}",
            f"#SBATCH --output={job_dir}/slurm-%j.out",
            f"#SBATCH --error={job_dir}/slurm-%j.err",
            f"#SBATCH --chdir={job_dir}",
        ]
        
        # Add optional Slurm parameters
        if resources.partition or self.settings.slurm_partition:
            script_lines.append(f"#SBATCH --partition={resources.partition or self.settings.slurm_partition}")
        
        if resources.account or self.settings.slurm_account:
            script_lines.append(f"#SBATCH --account={resources.account or self.settings.slurm_account}")
        
        if resources.qos or self.settings.slurm_qos:
            script_lines.append(f"#SBATCH --qos={resources.qos or self.settings.slurm_qos}")
        
        script_lines.extend([
            "",
            "# Load required modules",
        ])
        
        for module in self.settings.slurm_modules:
            script_lines.append(f"module load {module}")
        
        script_lines.extend([
            "",
            "# Set up environment",
            "set -e",
            "export BIO_JOB_ID=" + job_id,
            "export BIO_JOB_TYPE=" + job_type,
            "export BIO_WORK_DIR=" + str(job_dir),
            "",
            "# Update job status to running",
            f"echo 'Job {job_id} starting at $(date)'",
            "",
            "# Execute the bioinformatics task",
        ])
        
        # Add task-specific execution command
        script_lines.append(self._get_task_command(job_type, parameters, job_dir))
        
        script_lines.extend([
            "",
            f"echo 'Job {job_id} completed at $(date)'",
        ])
        
        # Write script file
        with open(script_path, 'w') as f:
            f.write('\n'.join(script_lines))
        
        # Make executable
        script_path.chmod(0o755)
        
        return script_path
    
    def _get_task_command(self, job_type: str, parameters: Dict[str, Any], job_dir: Path) -> str:
        """Generate the command for the specific bioinformatics task"""
        if job_type in ["blastn", "blastp", "blastx"]:
            return self._get_blast_command(job_type, parameters, job_dir)
        elif job_type == "makeblastdb":
            return self._get_makeblastdb_command(parameters, job_dir)
        else:
            # Generic command - could be expanded for other tools
            return f"echo 'Unknown job type: {job_type}'; exit 1"
    
    def _get_blast_command(self, job_type: str, parameters: Dict[str, Any], job_dir: Path) -> str:
        """Generate BLAST command"""
        query_file = job_dir / "query.fasta"
        output_file = job_dir / "blast_results.json"
        
        # Download query file
        download_cmd = f"# Download query file from {parameters.get('query_url', 'unknown')}"
        
        # BLAST command
        blast_cmd = [
            job_type,
            "-query", str(query_file),
            "-db", parameters.get("database", "nr"),
            "-evalue", str(parameters.get("evalue", 10.0)),
            "-max_target_seqs", str(parameters.get("max_hits", 50)),
            "-outfmt", "15",  # JSON format
            "-out", str(output_file),
            "-num_threads", "$SLURM_CPUS_PER_TASK"
        ]
        
        return f"""
# Download input files
python3 -c "
import sys
sys.path.append('/path/to/bio-mcp-queue/src')
from bio.storage import StorageClient
storage = StorageClient()
storage.download_file('{parameters.get('query_url', '')}', '{query_file}')
"

# Run BLAST
{' '.join(blast_cmd)}

# Upload results
python3 -c "
import sys
sys.path.append('/path/to/bio-mcp-queue/src')
from bio.storage import StorageClient
from bio.models import JobStatus
storage = StorageClient()
result_url = storage.upload_file('{output_file}', 'results/{job_dir.name}/blast_output.json')
storage.update_job_status('{job_dir.name}', JobStatus.COMPLETED, result={{'result_url': result_url}})
"
"""
    
    def _get_makeblastdb_command(self, parameters: Dict[str, Any], job_dir: Path) -> str:
        """Generate makeblastdb command"""
        input_file = job_dir / "input.fasta"
        db_name = parameters.get("database_name", "custom_db")
        
        return f"""
# Download input file
python3 -c "
import sys
sys.path.append('/path/to/bio-mcp-queue/src')
from bio.storage import StorageClient
storage = StorageClient()
storage.download_file('{parameters.get('input_url', '')}', '{input_file}')
"

# Create BLAST database
makeblastdb -in {input_file} -out {job_dir / db_name} -dbtype {parameters.get('dbtype', 'nucl')} -title "{parameters.get('title', db_name)}" -parse_seqids

# Upload database files
python3 -c "
import sys
sys.path.append('/path/to/bio-mcp-queue/src')
from bio.storage import StorageClient
from bio.models import JobStatus
from pathlib import Path
storage = StorageClient()
db_files = list(Path('{job_dir}').glob('{db_name}.*'))
db_urls = {{}}
for db_file in db_files:
    url = storage.upload_file(db_file, f'databases/{job_dir.name}/{{db_file.name}}')
    db_urls[str(db_file.suffix)] = url
storage.update_job_status('{job_dir.name}', JobStatus.COMPLETED, result={{'database_files': db_urls}})
"
"""
    
    async def submit_job(
        self,
        job_id: str,
        job_type: str,
        parameters: Dict[str, Any],
        resources: Optional[ResourceRequest] = None,
        priority: int = 5
    ) -> str:
        """Submit job to Slurm"""
        try:
            # Set default resources
            if resources is None:
                resources = ResourceRequest(
                    cpus=self.settings.slurm_default_cpus,
                    memory_mb=self.settings.slurm_default_memory_mb,
                    walltime_minutes=self.settings.slurm_default_walltime_minutes
                )
            
            # Create job script
            script_path = self._create_job_script(job_id, job_type, parameters, resources)
            
            # Submit to Slurm
            cmd = ["sbatch", str(script_path)]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=script_path.parent
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                raise RuntimeError(f"sbatch failed: {stderr.decode()}")
            
            # Parse Slurm job ID from output
            output = stdout.decode().strip()
            slurm_job_id = output.split()[-1]
            
            # Update job status
            self.storage.update_job_status(
                job_id,
                JobStatus.PENDING,
                result={"slurm_job_id": slurm_job_id, "script_path": str(script_path)}
            )
            
            logger.info(f"Submitted job {job_id} to Slurm as {slurm_job_id}")
            return slurm_job_id
            
        except Exception as e:
            logger.error(f"Failed to submit job {job_id}: {e}")
            self.storage.update_job_status(job_id, JobStatus.FAILED, error=str(e))
            raise
    
    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get job status from Slurm"""
        try:
            job_info = self.storage.get_job_info(job_id)
            if not job_info or "slurm_job_id" not in job_info.get("result", {}):
                return JobStatus.PENDING
            
            slurm_job_id = job_info["result"]["slurm_job_id"]
            
            # Query Slurm for job status
            cmd = ["squeue", "-j", slurm_job_id, "-h", "-o", "%T"]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                # Job might be completed, check sacct
                return await self._check_completed_job(slurm_job_id)
            
            slurm_state = stdout.decode().strip()
            
            # Map Slurm states to our JobStatus
            state_map = {
                "PENDING": JobStatus.PENDING,
                "RUNNING": JobStatus.RUNNING,
                "COMPLETED": JobStatus.COMPLETED,
                "FAILED": JobStatus.FAILED,
                "CANCELLED": JobStatus.CANCELLED,
                "TIMEOUT": JobStatus.FAILED,
                "OUT_OF_MEMORY": JobStatus.FAILED,
                "NODE_FAIL": JobStatus.FAILED
            }
            
            return state_map.get(slurm_state, JobStatus.PENDING)
            
        except Exception as e:
            logger.error(f"Failed to get status for job {job_id}: {e}")
            return JobStatus.FAILED
    
    async def _check_completed_job(self, slurm_job_id: str) -> JobStatus:
        """Check completed job status using sacct"""
        try:
            cmd = ["sacct", "-j", slurm_job_id, "-n", "-o", "State"]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                return JobStatus.FAILED
            
            state = stdout.decode().strip().split('\n')[0].strip()
            
            if "COMPLETED" in state:
                return JobStatus.COMPLETED
            elif "FAILED" in state or "CANCELLED" in state:
                return JobStatus.FAILED
            else:
                return JobStatus.PENDING
                
        except Exception:
            return JobStatus.FAILED
    
    async def get_job_info(self, job_id: str) -> Optional[JobInfo]:
        """Get detailed job information"""
        job_data = self.storage.get_job_info(job_id)
        if not job_data:
            return None
        
        # Get current status from Slurm
        current_status = await self.get_job_status(job_id)
        
        # Update status if changed
        if current_status != job_data.get("status"):
            self.storage.update_job_status(job_id, current_status)
            job_data["status"] = current_status
        
        return JobInfo(
            job_id=job_data["job_id"],
            job_type=job_data.get("job_type", "unknown"),
            status=job_data["status"],
            created_at=job_data["created_at"],
            updated_at=job_data["updated_at"],
            started_at=job_data.get("started_at"),
            completed_at=job_data.get("completed_at"),
            progress=job_data.get("progress"),
            result_url=job_data.get("result", {}).get("result_url") if isinstance(job_data.get("result"), dict) else None,
            error=job_data.get("error"),
            tags=job_data.get("tags", [])
        )
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a Slurm job"""
        try:
            job_info = self.storage.get_job_info(job_id)
            if not job_info or "slurm_job_id" not in job_info.get("result", {}):
                return False
            
            slurm_job_id = job_info["result"]["slurm_job_id"]
            
            cmd = ["scancel", slurm_job_id]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await result.communicate()
            
            if result.returncode == 0:
                self.storage.update_job_status(job_id, JobStatus.CANCELLED)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    async def list_jobs(
        self, 
        status: Optional[JobStatus] = None,
        limit: int = 100
    ) -> List[JobInfo]:
        """List jobs (implementation depends on storage backend)"""
        # This would need to be implemented based on how jobs are stored
        # For now, return empty list
        return []
    
    async def cleanup_old_jobs(self, days: int = 7):
        """Clean up old job directories and files"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            work_dir = Path(self.settings.slurm_work_dir)
            
            for job_dir in work_dir.iterdir():
                if job_dir.is_dir():
                    # Check if directory is older than cutoff
                    if datetime.fromtimestamp(job_dir.stat().st_mtime) < cutoff_date:
                        shutil.rmtree(job_dir)
                        logger.info(f"Cleaned up old job directory: {job_dir}")
                        
        except Exception as e:
            logger.error(f"Failed to cleanup old jobs: {e}")