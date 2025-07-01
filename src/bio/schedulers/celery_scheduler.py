import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from celery.result import AsyncResult

from .base import BaseScheduler, SchedulerType, ResourceRequest
from ..models import JobStatus, JobInfo, JobType
from ..storage import StorageClient
from ..tasks import run_blastn, run_blastp, make_blast_db
from ...celery_app import app as celery_app

logger = logging.getLogger(__name__)


class CeleryScheduler(BaseScheduler):
    """Celery-based job scheduler (wraps existing functionality)"""
    
    def __init__(self):
        self.storage = StorageClient()
        self.task_map = {
            "blastn": run_blastn,
            "blastp": run_blastp,
            "makeblastdb": make_blast_db,
        }
    
    @property
    def scheduler_type(self) -> SchedulerType:
        return SchedulerType.CELERY
    
    async def is_available(self) -> bool:
        """Check if Celery is available"""
        try:
            # Try to ping Celery workers
            active_workers = celery_app.control.inspect().active()
            return active_workers is not None and len(active_workers) > 0
        except Exception as e:
            logger.warning(f"Celery not available: {e}")
            return False
    
    async def submit_job(
        self,
        job_id: str,
        job_type: str,
        parameters: Dict[str, Any],
        resources: Optional[ResourceRequest] = None,
        priority: int = 5
    ) -> str:
        """Submit job to Celery"""
        try:
            # Get task function
            task_func = self.task_map.get(job_type)
            if not task_func:
                raise ValueError(f"Unknown job type: {job_type}")
            
            # Prepare task parameters
            task_params = parameters.copy()
            task_params["job_id"] = job_id
            
            # Submit to Celery
            result = task_func.apply_async(
                kwargs=task_params,
                task_id=job_id,
                priority=priority
            )
            
            # Store initial job info
            self.storage.update_job_status(
                job_id,
                JobStatus.PENDING,
                result={"celery_task_id": job_id}
            )
            
            logger.info(f"Submitted job {job_id} to Celery")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to submit job {job_id}: {e}")
            self.storage.update_job_status(job_id, JobStatus.FAILED, error=str(e))
            raise
    
    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get job status from Celery"""
        try:
            # First check storage
            job_data = self.storage.get_job_info(job_id)
            if job_data and job_data.get("status") in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                return job_data["status"]
            
            # Check Celery
            result = AsyncResult(job_id, app=celery_app)
            
            state_map = {
                "PENDING": JobStatus.PENDING,
                "STARTED": JobStatus.RUNNING,
                "SUCCESS": JobStatus.COMPLETED,
                "FAILURE": JobStatus.FAILED,
                "RETRY": JobStatus.RUNNING,
                "REVOKED": JobStatus.CANCELLED
            }
            
            celery_status = state_map.get(result.state, JobStatus.PENDING)
            
            # Update storage if status changed
            if not job_data or job_data.get("status") != celery_status:
                self.storage.update_job_status(job_id, celery_status)
            
            return celery_status
            
        except Exception as e:
            logger.error(f"Failed to get status for job {job_id}: {e}")
            return JobStatus.FAILED
    
    async def get_job_info(self, job_id: str) -> Optional[JobInfo]:
        """Get detailed job information"""
        job_data = self.storage.get_job_info(job_id)
        
        if not job_data:
            # Try to get from Celery
            result = AsyncResult(job_id, app=celery_app)
            if result.state == "PENDING" and not result.info:
                return None
            
            state_map = {
                "PENDING": JobStatus.PENDING,
                "STARTED": JobStatus.RUNNING,
                "SUCCESS": JobStatus.COMPLETED,
                "FAILURE": JobStatus.FAILED,
                "RETRY": JobStatus.RUNNING,
                "REVOKED": JobStatus.CANCELLED
            }
            
            job_data = {
                "job_id": job_id,
                "status": state_map.get(result.state, JobStatus.PENDING),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
        else:
            # Update status from Celery if needed
            current_status = await self.get_job_status(job_id)
            if current_status != job_data.get("status"):
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
        """Cancel a Celery job"""
        try:
            result = AsyncResult(job_id, app=celery_app)
            result.revoke(terminate=True)
            
            self.storage.update_job_status(job_id, JobStatus.CANCELLED)
            
            logger.info(f"Cancelled job {job_id}")
            return True
            
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
        """Clean up old job records"""
        # Use existing storage cleanup
        self.storage.cleanup_old_files(days)