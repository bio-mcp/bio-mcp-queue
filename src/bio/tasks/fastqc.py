"""
FastQC tasks for bio-mcp-queue system
"""
import asyncio
import tempfile
from pathlib import Path
from typing import Dict, Any

from celery import Celery
from ..models import JobResult


def run_fastqc_single(parameters: dict) -> Dict[str, Any]:
    """
    Execute FastQC on a single file
    """
    try:
        input_file = parameters["input_file"]
        threads = parameters.get("threads", 1)
        contaminants = parameters.get("contaminants")
        adapters = parameters.get("adapters")
        limits = parameters.get("limits")
        
        # Validate input file exists
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "fastqc_output"
            output_dir.mkdir()
            
            # Build FastQC command
            cmd = [
                "fastqc",
                "--outdir", str(output_dir),
                "--threads", str(threads),
                "--extract"
            ]
            
            # Add optional parameters
            if contaminants:
                cmd.extend(["--contaminants", contaminants])
            if adapters:
                cmd.extend(["--adapters", adapters])
            if limits:
                cmd.extend(["--limits", limits])
            
            cmd.append(str(input_path))
            
            # Execute FastQC
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            
            if result.returncode != 0:
                raise RuntimeError(f"FastQC failed: {result.stderr}")
            
            # Parse results
            summary = _parse_fastqc_results(output_dir, input_path.stem)
            
            return {
                "success": True,
                "summary": summary,
                "files_processed": 1,
                "output_directory": str(output_dir),
                "command": " ".join(cmd),
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def run_fastqc_batch(parameters: dict) -> Dict[str, Any]:
    """
    Execute FastQC on multiple files in a directory
    """
    try:
        input_dir = parameters["input_dir"]
        file_pattern = parameters.get("file_pattern", "*.fastq*")
        threads = parameters.get("threads", 4)
        
        # Validate input directory
        input_path = Path(input_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")
        
        # Find files
        files = list(input_path.glob(file_pattern))
        if not files:
            raise ValueError(f"No files found matching pattern '{file_pattern}' in {input_dir}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "fastqc_batch_output"
            output_dir.mkdir()
            
            # Build FastQC command for batch processing
            cmd = [
                "fastqc",
                "--outdir", str(output_dir),
                "--threads", str(threads),
                "--extract"
            ] + [str(f) for f in files]
            
            # Execute FastQC
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            
            if result.returncode != 0:
                raise RuntimeError(f"FastQC batch processing failed: {result.stderr}")
            
            # Analyze results
            summary = _analyze_batch_results(output_dir, files)
            
            return {
                "success": True,
                "summary": summary,
                "files_processed": len(files),
                "output_directory": str(output_dir),
                "command": " ".join(cmd[:10]) + f" ... ({len(files)} files)",
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def run_multiqc_report(parameters: dict) -> Dict[str, Any]:
    """
    Generate MultiQC report from analysis results
    """
    try:
        input_dir = parameters["input_dir"]
        title = parameters.get("title")
        comment = parameters.get("comment")
        template = parameters.get("template", "default")
        
        # Validate input directory
        input_path = Path(input_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "multiqc_output"
            output_dir.mkdir()
            
            # Build MultiQC command
            cmd = [
                "multiqc",
                str(input_path),
                "--outdir", str(output_dir),
                "--template", template
            ]
            
            if title:
                cmd.extend(["--title", title])
            if comment:
                cmd.extend(["--comment", comment])
            
            # Execute MultiQC
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                raise RuntimeError(f"MultiQC failed: {result.stderr}")
            
            # Get report information
            report_html = output_dir / "multiqc_report.html"
            data_dir = output_dir / "multiqc_data"
            
            summary = {
                "report_generated": report_html.exists(),
                "report_size": report_html.stat().st_size if report_html.exists() else 0,
                "data_directory": str(data_dir) if data_dir.exists() else None
            }
            
            # Parse general statistics if available
            if (data_dir / "multiqc_general_stats.txt").exists():
                with open(data_dir / "multiqc_general_stats.txt") as f:
                    stats_preview = f.read()[:500]  # First 500 chars
                    summary["general_stats_preview"] = stats_preview
            
            return {
                "success": True,
                "summary": summary,
                "output_directory": str(output_dir),
                "command": " ".join(cmd),
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def _parse_fastqc_results(output_dir: Path, filename_base: str) -> Dict[str, Any]:
    """Parse FastQC results and return summary statistics"""
    try:
        # Find FastQC output directory
        fastqc_dir = None
        for item in output_dir.iterdir():
            if item.is_dir() and filename_base in item.name:
                fastqc_dir = item
                break
        
        if not fastqc_dir:
            return {"error": "FastQC output directory not found"}
        
        summary = {}
        
        # Parse summary file for pass/warn/fail counts
        summary_file = fastqc_dir / "summary.txt"
        if summary_file.exists():
            with open(summary_file) as f:
                lines = f.readlines()
                
            pass_count = sum(1 for line in lines if line.startswith('PASS'))
            warn_count = sum(1 for line in lines if line.startswith('WARN'))
            fail_count = sum(1 for line in lines if line.startswith('FAIL'))
            
            summary.update({
                "modules_pass": pass_count,
                "modules_warn": warn_count,
                "modules_fail": fail_count,
                "total_modules": len(lines)
            })
        
        # Parse basic statistics from data file
        data_file = fastqc_dir / "fastqc_data.txt"
        if data_file.exists():
            with open(data_file) as f:
                content = f.read()
                
            # Extract key metrics
            lines = content.split('\n')
            in_basic_stats = False
            
            for line in lines:
                if line.startswith('>>Basic Statistics'):
                    in_basic_stats = True
                    continue
                elif line.startswith('>>END_MODULE'):
                    in_basic_stats = False
                    continue
                elif in_basic_stats and '\t' in line and not line.startswith('#'):
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        key = parts[0].lower().replace(' ', '_')
                        summary[key] = parts[1]
        
        return summary
        
    except Exception as e:
        return {"error": f"Error parsing FastQC results: {str(e)}"}


def _analyze_batch_results(output_dir: Path, files: list) -> Dict[str, Any]:
    """Analyze batch FastQC results and return summary"""
    try:
        total_pass = total_warn = total_fail = 0
        files_with_issues = []
        
        for input_file in files:
            # Find corresponding FastQC directory
            base_name = input_file.stem.replace('.fastq', '').replace('.fq', '')
            fastqc_dir = None
            
            for item in output_dir.iterdir():
                if item.is_dir() and base_name in item.name:
                    fastqc_dir = item
                    break
            
            if fastqc_dir and (fastqc_dir / "summary.txt").exists():
                with open(fastqc_dir / "summary.txt") as f:
                    summary_lines = f.readlines()
                    
                pass_count = sum(1 for line in summary_lines if line.startswith('PASS'))
                warn_count = sum(1 for line in summary_lines if line.startswith('WARN'))
                fail_count = sum(1 for line in summary_lines if line.startswith('FAIL'))
                
                total_pass += pass_count
                total_warn += warn_count
                total_fail += fail_count
                
                if warn_count > 0 or fail_count > 0:
                    files_with_issues.append({
                        "file": input_file.name,
                        "warnings": warn_count,
                        "failures": fail_count
                    })
        
        return {
            "total_pass": total_pass,
            "total_warn": total_warn,
            "total_fail": total_fail,
            "files_with_issues": files_with_issues,
            "files_processed": len(files)
        }
        
    except Exception as e:
        return {"error": f"Error analyzing batch results: {str(e)}"}


# Register tasks with Celery
def register_fastqc_tasks(celery_app: Celery):
    """Register FastQC tasks with the Celery app"""
    
    @celery_app.task(bind=True, name="fastqc_single")
    def fastqc_single_task(self, parameters: dict):
        """Celery task for single FastQC analysis"""
        self.update_state(state="PROGRESS", meta={"status": "Running FastQC analysis..."})
        return run_fastqc_single(parameters)
    
    @celery_app.task(bind=True, name="fastqc_batch")
    def fastqc_batch_task(self, parameters: dict):
        """Celery task for batch FastQC analysis"""
        self.update_state(state="PROGRESS", meta={"status": "Running batch FastQC analysis..."})
        return run_fastqc_batch(parameters)
    
    @celery_app.task(bind=True, name="multiqc_report")
    def multiqc_report_task(self, parameters: dict):
        """Celery task for MultiQC report generation"""
        self.update_state(state="PROGRESS", meta={"status": "Generating MultiQC report..."})
        return run_multiqc_report(parameters)
    
    return {
        "fastqc_single": fastqc_single_task,
        "fastqc_batch": fastqc_batch_task,
        "multiqc_report": multiqc_report_task
    }