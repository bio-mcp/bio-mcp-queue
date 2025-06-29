"""
REST API for job submission and monitoring
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import uuid
from datetime import datetime

from bio.models import JobRequest, JobInfo, JobStatus, QueueStats
from bio.storage import StorageClient
from bio.tasks import run_blastn, run_blastp, make_blast_db
from celery.result import AsyncResult
from celery_app import app as celery_app

app = FastAPI(title="Bio-MCP Job Queue API", version="0.1.0")

# CORS for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = StorageClient()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/jobs/submit", response_model=JobInfo)
async def submit_job(job_request: JobRequest):
    """Submit a new job to the queue"""
    try:
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Map job type to task
        task_map = {
            "blastn": run_blastn,
            "blastp": run_blastp,
            "makeblastdb": make_blast_db,
        }
        
        task_func = task_map.get(job_request.job_type)
        if not task_func:
            raise HTTPException(400, f"Unknown job type: {job_request.job_type}")
        
        # Submit to Celery
        task_params = job_request.parameters.copy()
        task_params["job_id"] = job_id
        
        result = task_func.apply_async(
            kwargs=task_params,
            task_id=job_id,
            priority=job_request.priority
        )
        
        # Store initial job info
        job_info = JobInfo(
            job_id=job_id,
            job_type=job_request.job_type,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            tags=job_request.tags
        )
        
        storage.update_job_status(
            job_id,
            JobStatus.PENDING,
            result={"celery_task_id": job_id}
        )
        
        return job_info
        
    except Exception as e:
        raise HTTPException(500, f"Failed to submit job: {str(e)}")


@app.get("/jobs/{job_id}/status", response_model=JobInfo)
async def get_job_status(job_id: str):
    """Get job status"""
    job_data = storage.get_job_info(job_id)
    
    if not job_data:
        # Try to get from Celery
        result = AsyncResult(job_id, app=celery_app)
        if result.state == "PENDING" and not result.info:
            raise HTTPException(404, f"Job {job_id} not found")
        
        status_map = {
            "PENDING": JobStatus.PENDING,
            "STARTED": JobStatus.RUNNING,
            "SUCCESS": JobStatus.COMPLETED,
            "FAILURE": JobStatus.FAILED,
            "RETRY": JobStatus.RUNNING,
            "REVOKED": JobStatus.CANCELLED
        }
        
        job_data = {
            "job_id": job_id,
            "status": status_map.get(result.state, JobStatus.PENDING),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
    
    # Convert to JobInfo
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


@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str):
    """Get job results"""
    job_data = storage.get_job_info(job_id)
    
    if not job_data:
        raise HTTPException(404, f"Job {job_id} not found")
    
    if job_data["status"] != JobStatus.COMPLETED:
        raise HTTPException(400, f"Job not completed. Current status: {job_data['status']}")
    
    return job_data.get("result", {})


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job"""
    try:
        result = AsyncResult(job_id, app=celery_app)
        result.revoke(terminate=True)
        
        storage.update_job_status(job_id, JobStatus.CANCELLED)
        
        return {"message": f"Job {job_id} cancelled"}
        
    except Exception as e:
        raise HTTPException(500, f"Failed to cancel job: {str(e)}")


@app.get("/queues/stats", response_model=List[QueueStats])
async def get_queue_stats():
    """Get queue statistics"""
    # This would query Celery/Redis for real stats
    # For now, return mock data
    return [
        QueueStats(
            queue_name="blast",
            pending_jobs=5,
            running_jobs=2,
            completed_jobs_24h=150,
            failed_jobs_24h=3,
            avg_runtime_seconds=45.5,
            workers_available=4
        ),
        QueueStats(
            queue_name="alignment",
            pending_jobs=2,
            running_jobs=1,
            completed_jobs_24h=80,
            failed_jobs_24h=1,
            avg_runtime_seconds=120.3,
            workers_available=2
        )
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)