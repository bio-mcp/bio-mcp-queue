import os
from pathlib import Path
from typing import Optional, Dict, Any
from minio import Minio
from minio.error import S3Error
import json
import redis
from datetime import datetime, timedelta
import logging
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class StorageSettings(BaseSettings):
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    bucket_name: str = "bio-mcp-jobs"
    redis_url: str = "redis://localhost:6379/2"
    
    class Config:
        env_prefix = "BIO_STORAGE_"


class StorageClient:
    """Handles file storage and job metadata"""
    
    def __init__(self, settings: Optional[StorageSettings] = None):
        self.settings = settings or StorageSettings()
        
        # Initialize MinIO client
        self.minio_client = Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure
        )
        
        # Initialize Redis client for job metadata
        self.redis_client = redis.from_url(self.settings.redis_url)
        
        # Ensure bucket exists
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        """Create bucket if it doesn't exist"""
        try:
            if not self.minio_client.bucket_exists(self.settings.bucket_name):
                self.minio_client.make_bucket(self.settings.bucket_name)
                logger.info(f"Created bucket: {self.settings.bucket_name}")
        except S3Error as e:
            logger.error(f"Error creating bucket: {e}")
            raise
    
    def upload_file(self, file_path: Path, object_name: str) -> str:
        """Upload file to MinIO and return URL"""
        try:
            self.minio_client.fput_object(
                self.settings.bucket_name,
                object_name,
                str(file_path)
            )
            
            # Generate presigned URL (valid for 7 days)
            url = self.minio_client.presigned_get_object(
                self.settings.bucket_name,
                object_name,
                expires=timedelta(days=7)
            )
            
            logger.info(f"Uploaded {file_path} to {object_name}")
            return url
            
        except S3Error as e:
            logger.error(f"Error uploading file: {e}")
            raise
    
    def download_file(self, url: str, destination: Path):
        """Download file from URL or MinIO object name"""
        try:
            # Extract object name from URL if it's a presigned URL
            if url.startswith("http"):
                # Parse object name from URL
                object_name = url.split("?")[0].split("/")[-1]
            else:
                object_name = url
            
            self.minio_client.fget_object(
                self.settings.bucket_name,
                object_name,
                str(destination)
            )
            
            logger.info(f"Downloaded {object_name} to {destination}")
            
        except S3Error as e:
            logger.error(f"Error downloading file: {e}")
            raise
    
    def update_job_status(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[float] = None
    ):
        """Update job status in Redis"""
        job_key = f"job:{job_id}"
        
        # Get existing job data
        job_data = self.redis_client.hgetall(job_key)
        if job_data:
            job_data = {k.decode(): v.decode() for k, v in job_data.items()}
            job_data = json.loads(job_data.get("data", "{}"))
        else:
            job_data = {"job_id": job_id, "created_at": datetime.utcnow().isoformat()}
        
        # Update fields
        job_data.update({
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        })
        
        if status == "running" and "started_at" not in job_data:
            job_data["started_at"] = datetime.utcnow().isoformat()
        
        if status in ["completed", "failed"]:
            job_data["completed_at"] = datetime.utcnow().isoformat()
        
        if result:
            job_data["result"] = result
        
        if error:
            job_data["error"] = error
        
        if progress is not None:
            job_data["progress"] = progress
        
        # Save to Redis
        self.redis_client.hset(job_key, "data", json.dumps(job_data))
        self.redis_client.expire(job_key, 604800)  # Expire after 7 days
        
        # Update status index
        self.redis_client.sadd(f"jobs:{status}", job_id)
        
        logger.info(f"Updated job {job_id} status to {status}")
    
    def get_job_info(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job information"""
        job_key = f"job:{job_id}"
        job_data = self.redis_client.hget(job_key, "data")
        
        if job_data:
            return json.loads(job_data)
        
        return None
    
    def cleanup_old_files(self, days: int = 7):
        """Clean up files older than specified days"""
        # This would be run as a scheduled task
        # Implementation depends on MinIO object lifecycle policies
        pass