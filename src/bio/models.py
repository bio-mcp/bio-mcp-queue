from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    BLAST_N = "blastn"
    BLAST_P = "blastp"
    BLAST_X = "blastx"
    MAKE_BLAST_DB = "makeblastdb"
    BWA_MEM = "bwa_mem"
    SAMTOOLS_SORT = "samtools_sort"
    SAMTOOLS_INDEX = "samtools_index"
    BCFTOOLS_CALL = "bcftools_call"


class JobRequest(BaseModel):
    """Base job request model"""
    job_type: JobType
    parameters: Dict[str, Any]
    priority: int = Field(default=5, ge=1, le=10)
    tags: List[str] = Field(default_factory=list)
    notification_email: Optional[str] = None


class BlastJobRequest(JobRequest):
    """BLAST-specific job request"""
    job_type: JobType = JobType.BLAST_N
    parameters: Dict[str, Any] = Field(
        ...,
        example={
            "query_file": "path/to/query.fasta",
            "database": "nr",
            "evalue": 0.001,
            "max_hits": 100,
            "output_format": "json"
        }
    )


class JobInfo(BaseModel):
    """Job information returned to client"""
    job_id: str
    job_type: JobType
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[float] = Field(None, ge=0, le=100)
    result_url: Optional[str] = None
    error: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class BlastJobResult(BaseModel):
    """BLAST job result"""
    job_id: str
    status: JobStatus
    result_url: str
    summary: Dict[str, Any] = Field(
        default_factory=dict,
        example={
            "query_title": "Query_1",
            "query_len": 500,
            "num_hits": 25,
            "best_hit_evalue": 1e-50,
            "best_hit_identity": 98.5
        }
    )
    completed_at: datetime
    runtime_seconds: float


class QueueStats(BaseModel):
    """Queue statistics"""
    queue_name: str
    pending_jobs: int
    running_jobs: int
    completed_jobs_24h: int
    failed_jobs_24h: int
    avg_runtime_seconds: float
    workers_available: int