from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel

from ..models import JobStatus, JobInfo


class SchedulerType(str, Enum):
    CELERY = "celery"
    SLURM = "slurm"


class ResourceRequest(BaseModel):
    """Resource requirements for a job"""
    cpus: int = 1
    memory_mb: int = 1024
    walltime_minutes: int = 60
    queue: Optional[str] = None
    partition: Optional[str] = None
    account: Optional[str] = None
    qos: Optional[str] = None


class BaseScheduler(ABC):
    """Abstract base class for job schedulers"""
    
    @abstractmethod
    async def submit_job(
        self,
        job_id: str,
        job_type: str,
        parameters: Dict[str, Any],
        resources: Optional[ResourceRequest] = None,
        priority: int = 5
    ) -> str:
        """
        Submit a job to the scheduler
        
        Args:
            job_id: Unique job identifier
            job_type: Type of job (blastn, blastp, etc.)
            parameters: Job parameters
            resources: Resource requirements
            priority: Job priority (1-10)
            
        Returns:
            Scheduler-specific job ID
        """
        pass
    
    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get job status"""
        pass
    
    @abstractmethod
    async def get_job_info(self, job_id: str) -> Optional[JobInfo]:
        """Get detailed job information"""
        pass
    
    @abstractmethod
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job"""
        pass
    
    @abstractmethod
    async def list_jobs(
        self, 
        status: Optional[JobStatus] = None,
        limit: int = 100
    ) -> List[JobInfo]:
        """List jobs, optionally filtered by status"""
        pass
    
    @abstractmethod
    async def cleanup_old_jobs(self, days: int = 7):
        """Clean up old job records"""
        pass
    
    @property
    @abstractmethod
    def scheduler_type(self) -> SchedulerType:
        """Return the scheduler type"""
        pass
    
    @abstractmethod
    async def is_available(self) -> bool:
        """Check if scheduler is available and configured"""
        pass