"""
REST API for job submission and monitoring
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import uuid
from datetime import datetime
import logging

from bio.models import JobRequest, JobInfo, JobStatus, QueueStats
from bio.storage import StorageClient
from bio.schedulers.factory import get_scheduler, get_scheduler_config_status, detect_available_schedulers, validate_scheduler_config
from bio.schedulers.base import ResourceRequest

logger = logging.getLogger(__name__)

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
    try:
        # Check scheduler availability
        available_schedulers = await detect_available_schedulers()
        config_status = get_scheduler_config_status()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "schedulers": available_schedulers,
            "config": config_status
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }


@app.post("/jobs/submit", response_model=JobInfo)
async def submit_job(job_request: JobRequest):
    """Submit a new job to the queue"""
    try:
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Get scheduler
        scheduler = await get_scheduler()
        
        # Create resource request from job parameters
        resources = None
        if "resources" in job_request.parameters:
            res_params = job_request.parameters["resources"]
            resources = ResourceRequest(
                cpus=res_params.get("cpus", 1),
                memory_mb=res_params.get("memory_mb", 1024),
                walltime_minutes=res_params.get("walltime_minutes", 60),
                partition=res_params.get("partition"),
                account=res_params.get("account"),
                qos=res_params.get("qos")
            )
        
        # Submit job to scheduler
        scheduler_job_id = await scheduler.submit_job(
            job_id=job_id,
            job_type=job_request.job_type,
            parameters=job_request.parameters,
            resources=resources,
            priority=job_request.priority
        )
        
        # Create job info response
        job_info = JobInfo(
            job_id=job_id,
            job_type=job_request.job_type,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            tags=job_request.tags
        )
        
        # Add scheduler info to storage
        storage.update_job_status(
            job_id,
            JobStatus.PENDING,
            result={
                "scheduler_type": scheduler.scheduler_type,
                "scheduler_job_id": scheduler_job_id,
                "job_type": job_request.job_type
            }
        )
        
        logger.info(f"Submitted job {job_id} to {scheduler.scheduler_type} scheduler as {scheduler_job_id}")
        return job_info
        
    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(500, f"Failed to submit job: {str(e)}")


@app.get("/jobs/{job_id}/status", response_model=JobInfo)
async def get_job_status(job_id: str):
    """Get job status"""
    try:
        # First check storage for job info
        job_data = storage.get_job_info(job_id)
        
        if not job_data:
            raise HTTPException(404, f"Job {job_id} not found")
        
        # Get scheduler type from job data
        scheduler_type = job_data.get("result", {}).get("scheduler_type", "celery")
        
        # Get appropriate scheduler and query current status
        scheduler = await get_scheduler(scheduler_type)
        job_info = await scheduler.get_job_info(job_id)
        
        if not job_info:
            raise HTTPException(404, f"Job {job_id} not found in scheduler")
        
        return job_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status for {job_id}: {e}")
        raise HTTPException(500, f"Failed to get job status: {str(e)}")


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
        # Get job data to determine scheduler
        job_data = storage.get_job_info(job_id)
        
        if not job_data:
            raise HTTPException(404, f"Job {job_id} not found")
        
        # Get scheduler type from job data
        scheduler_type = job_data.get("result", {}).get("scheduler_type", "celery")
        
        # Get appropriate scheduler and cancel job
        scheduler = await get_scheduler(scheduler_type)
        success = await scheduler.cancel_job(job_id)
        
        if success:
            return {"message": f"Job {job_id} cancelled"}
        else:
            raise HTTPException(400, f"Failed to cancel job {job_id}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        raise HTTPException(500, f"Failed to cancel job: {str(e)}")


@app.get("/queues/stats", response_model=List[QueueStats])
async def get_queue_stats():
    """Get queue statistics"""
    # This would query scheduler for real stats
    # For now, return mock data
    try:
        scheduler = await get_scheduler()
        
        # Return scheduler-specific mock data
        if scheduler.scheduler_type == "slurm":
            return [
                QueueStats(
                    queue_name="slurm",
                    pending_jobs=3,
                    running_jobs=5,
                    completed_jobs_24h=85,
                    failed_jobs_24h=2,
                    avg_runtime_seconds=180.2,
                    workers_available=10
                )
            ]
        else:
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
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return []


@app.get("/scheduler/status")
async def get_scheduler_status():
    """Get current scheduler status and configuration"""
    try:
        available = await detect_available_schedulers()
        config_status = get_scheduler_config_status()
        
        # Try to get current scheduler info
        try:
            current_scheduler = await get_scheduler()
            current_info = {
                "type": current_scheduler.scheduler_type,
                "available": True
            }
        except Exception as e:
            current_info = {
                "type": "none",
                "available": False,
                "error": str(e)
            }
        
        return {
            "current_scheduler": current_info,
            "available_schedulers": available,
            "configuration": config_status
        }
        
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        raise HTTPException(500, f"Failed to get scheduler status: {str(e)}")


@app.post("/scheduler/configure")
async def configure_scheduler_endpoint(config: dict):
    """Configure scheduler settings"""
    try:
        # This endpoint would typically update environment variables
        # or configuration files based on the provided config
        
        # For now, just validate the configuration
        scheduler_type = config.get("scheduler_type", "auto")
        validation = await validate_scheduler_config(scheduler_type)
        
        return {
            "message": "Configuration updated",
            "validation": validation
        }
        
    except Exception as e:
        logger.error(f"Failed to configure scheduler: {e}")
        raise HTTPException(500, f"Failed to configure scheduler: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)