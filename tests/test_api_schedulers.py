import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from src.api import app
from src.bio.schedulers.base import SchedulerType, ResourceRequest
from src.bio.schedulers.celery_scheduler import CeleryScheduler
from src.bio.schedulers.slurm_scheduler import SlurmScheduler
from src.bio.models import JobStatus, JobInfo


client = TestClient(app)


class TestAPISchedulerIntegration:
    """Test API endpoints with scheduler abstraction"""
    
    @patch('src.api.get_scheduler')
    @patch('src.api.detect_available_schedulers')
    @patch('src.api.get_scheduler_config_status')
    def test_health_check_with_schedulers(self, mock_config, mock_detect, mock_get_scheduler):
        """Test health check endpoint includes scheduler info"""
        # Mock scheduler detection
        mock_detect.return_value = {"celery": True, "slurm": False}
        mock_config.return_value = {"requested_scheduler": "auto"}
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "schedulers" in data
        assert "config" in data
        assert data["schedulers"]["celery"] is True
        assert data["schedulers"]["slurm"] is False
    
    @patch('src.api.get_scheduler')
    def test_submit_job_with_celery(self, mock_get_scheduler):
        """Test job submission with Celery scheduler"""
        # Mock Celery scheduler
        mock_scheduler = Mock(spec=CeleryScheduler)
        mock_scheduler.scheduler_type = SchedulerType.CELERY
        mock_scheduler.submit_job = AsyncMock(return_value="celery-job-123")
        mock_get_scheduler.return_value = mock_scheduler
        
        # Mock storage
        with patch('src.api.storage') as mock_storage:
            mock_storage.update_job_status = Mock()
            
            job_request = {
                "job_type": "blastn",
                "parameters": {
                    "query_url": "s3://bucket/query.fasta",
                    "database": "nr",
                    "evalue": 0.001
                },
                "priority": 5,
                "tags": ["test"]
            }
            
            response = client.post("/jobs/submit", json=job_request)
            
            assert response.status_code == 200
            data = response.json()
            assert data["job_type"] == "blastn"
            assert data["status"] == "pending"
            
            # Verify scheduler was called correctly
            mock_scheduler.submit_job.assert_called_once()
            args, kwargs = mock_scheduler.submit_job.call_args
            assert kwargs["job_type"] == "blastn"
            assert kwargs["parameters"]["database"] == "nr"
            assert kwargs["priority"] == 5
    
    @patch('src.api.get_scheduler')
    def test_submit_job_with_slurm(self, mock_get_scheduler):
        """Test job submission with Slurm scheduler"""
        # Mock Slurm scheduler
        mock_scheduler = Mock(spec=SlurmScheduler)
        mock_scheduler.scheduler_type = SchedulerType.SLURM
        mock_scheduler.submit_job = AsyncMock(return_value="12345")
        mock_get_scheduler.return_value = mock_scheduler
        
        # Mock storage
        with patch('src.api.storage') as mock_storage:
            mock_storage.update_job_status = Mock()
            
            job_request = {
                "job_type": "blastn",
                "parameters": {
                    "query_url": "s3://bucket/query.fasta",
                    "database": "nr",
                    "resources": {
                        "cpus": 4,
                        "memory_mb": 8192,
                        "walltime_minutes": 60,
                        "partition": "compute"
                    }
                },
                "priority": 7
            }
            
            response = client.post("/jobs/submit", json=job_request)
            
            assert response.status_code == 200
            
            # Verify scheduler was called with resource request
            mock_scheduler.submit_job.assert_called_once()
            args, kwargs = mock_scheduler.submit_job.call_args
            
            resources = kwargs["resources"]
            assert isinstance(resources, ResourceRequest)
            assert resources.cpus == 4
            assert resources.memory_mb == 8192
            assert resources.partition == "compute"
    
    @patch('src.api.get_scheduler')
    def test_submit_job_scheduler_failure(self, mock_get_scheduler):
        """Test job submission when scheduler fails"""
        # Mock scheduler that raises exception
        mock_scheduler = Mock()
        mock_scheduler.submit_job = AsyncMock(side_effect=Exception("Scheduler error"))
        mock_get_scheduler.return_value = mock_scheduler
        
        job_request = {
            "job_type": "blastn",
            "parameters": {"query_url": "test.fasta"}
        }
        
        response = client.post("/jobs/submit", json=job_request)
        
        assert response.status_code == 500
        assert "Failed to submit job" in response.json()["detail"]
    
    @patch('src.api.get_scheduler')
    def test_get_job_status_with_scheduler(self, mock_get_scheduler):
        """Test getting job status via scheduler"""
        # Mock scheduler
        mock_scheduler = Mock()
        mock_job_info = JobInfo(
            job_id="test-job-123",
            job_type="blastn",
            status=JobStatus.RUNNING,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:01:00",
            tags=[]
        )
        mock_scheduler.get_job_info = AsyncMock(return_value=mock_job_info)
        mock_get_scheduler.return_value = mock_scheduler
        
        # Mock storage
        with patch('src.api.storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"scheduler_type": "celery"}
            }
            
            response = client.get("/jobs/test-job-123/status")
            
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-123"
            assert data["status"] == "running"
    
    @patch('src.api.get_scheduler')
    def test_get_job_status_not_found(self, mock_get_scheduler):
        """Test getting status of non-existent job"""
        # Mock storage returning no job
        with patch('src.api.storage') as mock_storage:
            mock_storage.get_job_info.return_value = None
            
            response = client.get("/jobs/nonexistent/status")
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]
    
    @patch('src.api.get_scheduler')
    def test_cancel_job_with_scheduler(self, mock_get_scheduler):
        """Test job cancellation via scheduler"""
        # Mock scheduler
        mock_scheduler = Mock()
        mock_scheduler.cancel_job = AsyncMock(return_value=True)
        mock_get_scheduler.return_value = mock_scheduler
        
        # Mock storage
        with patch('src.api.storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"scheduler_type": "slurm"}
            }
            
            response = client.delete("/jobs/test-job-456")
            
            assert response.status_code == 200
            data = response.json()
            assert "cancelled" in data["message"]
            
            mock_scheduler.cancel_job.assert_called_once_with("test-job-456")
    
    @patch('src.api.get_scheduler')
    def test_cancel_job_failure(self, mock_get_scheduler):
        """Test job cancellation failure"""
        # Mock scheduler that fails to cancel
        mock_scheduler = Mock()
        mock_scheduler.cancel_job = AsyncMock(return_value=False)
        mock_get_scheduler.return_value = mock_scheduler
        
        # Mock storage
        with patch('src.api.storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"scheduler_type": "celery"}
            }
            
            response = client.delete("/jobs/test-job-fail")
            
            assert response.status_code == 400
            assert "Failed to cancel" in response.json()["detail"]
    
    @patch('src.api.detect_available_schedulers')
    @patch('src.api.get_scheduler_config_status')
    @patch('src.api.get_scheduler')
    def test_scheduler_status_endpoint(self, mock_get_scheduler, mock_config, mock_detect):
        """Test scheduler status endpoint"""
        # Mock successful scheduler
        mock_scheduler = Mock()
        mock_scheduler.scheduler_type = SchedulerType.CELERY
        mock_get_scheduler.return_value = mock_scheduler
        
        mock_detect.return_value = {"celery": True, "slurm": False}
        mock_config.return_value = {"requested_scheduler": "auto"}
        
        response = client.get("/scheduler/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["current_scheduler"]["type"] == "celery"
        assert data["current_scheduler"]["available"] is True
        assert data["available_schedulers"]["celery"] is True
    
    @patch('src.api.get_scheduler')
    def test_scheduler_status_no_scheduler(self, mock_get_scheduler):
        """Test scheduler status when no scheduler available"""
        mock_get_scheduler.side_effect = RuntimeError("No schedulers available")
        
        with patch('src.api.detect_available_schedulers') as mock_detect:
            with patch('src.api.get_scheduler_config_status') as mock_config:
                mock_detect.return_value = {"celery": False, "slurm": False}
                mock_config.return_value = {"requested_scheduler": "auto"}
                
                response = client.get("/scheduler/status")
                
                assert response.status_code == 200
                data = response.json()
                assert data["current_scheduler"]["type"] == "none"
                assert data["current_scheduler"]["available"] is False
    
    @patch('src.api.validate_scheduler_config')
    def test_configure_scheduler_endpoint(self, mock_validate):
        """Test scheduler configuration endpoint"""
        mock_validate.return_value = {
            "valid": True,
            "available_schedulers": {"celery": True},
            "recommendations": []
        }
        
        config = {
            "scheduler_type": "celery",
            "redis_url": "redis://localhost:6379/0"
        }
        
        response = client.post("/scheduler/configure", json=config)
        
        assert response.status_code == 200
        data = response.json()
        assert "Configuration updated" in data["message"]
        assert data["validation"]["valid"] is True
    
    @patch('src.api.get_scheduler')
    def test_queue_stats_celery(self, mock_get_scheduler):
        """Test queue stats endpoint with Celery"""
        mock_scheduler = Mock()
        mock_scheduler.scheduler_type = SchedulerType.CELERY
        mock_get_scheduler.return_value = mock_scheduler
        
        response = client.get("/queues/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(queue["queue_name"] == "blast" for queue in data)
    
    @patch('src.api.get_scheduler')
    def test_queue_stats_slurm(self, mock_get_scheduler):
        """Test queue stats endpoint with Slurm"""
        mock_scheduler = Mock()
        mock_scheduler.scheduler_type = SchedulerType.SLURM
        mock_get_scheduler.return_value = mock_scheduler
        
        response = client.get("/queues/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["queue_name"] == "slurm"