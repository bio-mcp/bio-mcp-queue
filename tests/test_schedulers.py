import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from src.bio.schedulers.factory import get_scheduler, detect_available_schedulers, validate_scheduler_config
from src.bio.schedulers.base import BaseScheduler, SchedulerType, ResourceRequest
from src.bio.schedulers.celery_scheduler import CeleryScheduler
from src.bio.schedulers.slurm_scheduler import SlurmScheduler, SlurmSettings
from src.bio.models import JobStatus


class TestSchedulerFactory:
    """Test scheduler factory and detection logic"""
    
    @pytest.mark.asyncio
    async def test_detect_available_schedulers(self):
        """Test scheduler detection"""
        available = await detect_available_schedulers()
        
        assert isinstance(available, dict)
        assert "celery" in available
        assert "slurm" in available
        assert isinstance(available["celery"], bool)
        assert isinstance(available["slurm"], bool)
    
    @pytest.mark.asyncio
    async def test_validate_scheduler_config(self):
        """Test scheduler configuration validation"""
        validation = await validate_scheduler_config("auto")
        
        assert isinstance(validation, dict)
        assert "valid" in validation
        assert "available_schedulers" in validation
        assert "recommendations" in validation
        assert "missing_config" in validation
    
    @pytest.mark.asyncio
    async def test_get_scheduler_auto_fallback(self):
        """Test auto scheduler selection with fallback"""
        # Mock availability to test fallback logic
        with patch('src.bio.schedulers.factory.detect_available_schedulers') as mock_detect:
            # Test Slurm available
            mock_detect.return_value = {"slurm": True, "celery": False}
            scheduler = await get_scheduler("auto")
            assert scheduler.scheduler_type == SchedulerType.SLURM
            
            # Test Celery available  
            mock_detect.return_value = {"slurm": False, "celery": True}
            scheduler = await get_scheduler("auto")
            assert scheduler.scheduler_type == SchedulerType.CELERY
            
            # Test neither available
            mock_detect.return_value = {"slurm": False, "celery": False}
            with pytest.raises(RuntimeError, match="No schedulers available"):
                await get_scheduler("auto")


class TestResourceRequest:
    """Test resource request model"""
    
    def test_resource_request_defaults(self):
        """Test default resource values"""
        req = ResourceRequest()
        assert req.cpus == 1
        assert req.memory_mb == 1024
        assert req.walltime_minutes == 60
        assert req.queue is None
        assert req.partition is None
    
    def test_resource_request_custom(self):
        """Test custom resource values"""
        req = ResourceRequest(
            cpus=4,
            memory_mb=8192,
            walltime_minutes=120,
            partition="gpu",
            account="mylab"
        )
        assert req.cpus == 4
        assert req.memory_mb == 8192
        assert req.walltime_minutes == 120
        assert req.partition == "gpu"
        assert req.account == "mylab"


class TestCeleryScheduler:
    """Test Celery scheduler implementation"""
    
    def test_scheduler_type(self):
        """Test scheduler type property"""
        scheduler = CeleryScheduler()
        assert scheduler.scheduler_type == SchedulerType.CELERY
    
    @pytest.mark.asyncio
    async def test_is_available_no_celery(self):
        """Test availability check when Celery is not available"""
        with patch('src.bio.schedulers.celery_scheduler.celery_app') as mock_app:
            mock_app.control.inspect.return_value.active.side_effect = Exception("Connection failed")
            
            scheduler = CeleryScheduler()
            available = await scheduler.is_available()
            assert available is False
    
    @pytest.mark.asyncio
    async def test_submit_job_unknown_type(self):
        """Test job submission with unknown job type"""
        scheduler = CeleryScheduler()
        
        with pytest.raises(ValueError, match="Unknown job type"):
            await scheduler.submit_job(
                job_id="test-123",
                job_type="unknown_tool",
                parameters={}
            )


class TestSlurmScheduler:
    """Test Slurm scheduler implementation"""
    
    def test_scheduler_type(self):
        """Test scheduler type property"""
        scheduler = SlurmScheduler()
        assert scheduler.scheduler_type == SchedulerType.SLURM
    
    def test_slurm_settings_defaults(self):
        """Test Slurm settings defaults"""
        settings = SlurmSettings()
        assert settings.slurm_default_cpus == 1
        assert settings.slurm_default_memory_mb == 1024
        assert settings.slurm_default_walltime_minutes == 60
        assert settings.slurm_work_dir == "/tmp/bio-mcp-jobs"
    
    @pytest.mark.asyncio
    async def test_is_available_no_slurm(self):
        """Test availability check when Slurm is not available"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = Mock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 1  # Command not found
            mock_subprocess.return_value = mock_process
            
            scheduler = SlurmScheduler()
            available = await scheduler.is_available()
            assert available is False
    
    @pytest.mark.asyncio
    async def test_is_available_with_slurm(self):
        """Test availability check when Slurm is available"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = Mock()
            mock_process.communicate.return_value = (b"/usr/bin/sbatch", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process
            
            scheduler = SlurmScheduler()
            available = await scheduler.is_available()
            assert available is True
    
    def test_create_job_script(self):
        """Test Slurm job script creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SlurmSettings(slurm_work_dir=tmpdir)
            scheduler = SlurmScheduler(settings)
            
            job_id = "test-job-123"
            job_type = "blastn"
            parameters = {
                "query_url": "s3://bucket/query.fasta",
                "database": "nr",
                "evalue": 0.001
            }
            resources = ResourceRequest(cpus=2, memory_mb=4096, walltime_minutes=30)
            
            script_path = scheduler._create_job_script(job_id, job_type, parameters, resources)
            
            assert script_path.exists()
            assert script_path.suffix == ".sh"
            
            # Check script content
            script_content = script_path.read_text()
            assert "#!/bin/bash" in script_content
            assert f"#SBATCH --job-name=bio-{job_type}-{job_id[:8]}" in script_content
            assert "#SBATCH --cpus-per-task=2" in script_content
            assert "#SBATCH --mem=4096M" in script_content
            assert "#SBATCH --time=30" in script_content
            assert f"export BIO_JOB_ID={job_id}" in script_content
    
    def test_create_job_script_with_slurm_options(self):
        """Test job script creation with Slurm-specific options"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SlurmSettings(
                slurm_work_dir=tmpdir,
                slurm_partition="compute",
                slurm_account="mylab",
                slurm_qos="normal"
            )
            scheduler = SlurmScheduler(settings)
            
            job_id = "test-job-456"
            parameters = {"test": True}
            resources = ResourceRequest()
            
            script_path = scheduler._create_job_script(job_id, "test", parameters, resources)
            script_content = script_path.read_text()
            
            assert "#SBATCH --partition=compute" in script_content
            assert "#SBATCH --account=mylab" in script_content
            assert "#SBATCH --qos=normal" in script_content
    
    @pytest.mark.asyncio
    async def test_submit_job_success(self):
        """Test successful job submission"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SlurmSettings(slurm_work_dir=tmpdir)
            scheduler = SlurmScheduler(settings)
            
            # Mock successful sbatch submission
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = Mock()
                mock_process.communicate.return_value = (b"Submitted batch job 12345", b"")
                mock_process.returncode = 0
                mock_subprocess.return_value = mock_process
                
                # Mock storage
                with patch.object(scheduler, 'storage') as mock_storage:
                    mock_storage.update_job_status = Mock()
                    
                    result = await scheduler.submit_job(
                        job_id="test-789",
                        job_type="blastn",
                        parameters={"query_url": "test.fasta"},
                        resources=ResourceRequest()
                    )
                    
                    assert result == "12345"
                    mock_storage.update_job_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_job_failure(self):
        """Test job submission failure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SlurmSettings(slurm_work_dir=tmpdir)
            scheduler = SlurmScheduler(settings)
            
            # Mock failed sbatch submission
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = Mock()
                mock_process.communicate.return_value = (b"", b"sbatch: error: invalid partition")
                mock_process.returncode = 1
                mock_subprocess.return_value = mock_process
                
                # Mock storage
                with patch.object(scheduler, 'storage') as mock_storage:
                    mock_storage.update_job_status = Mock()
                    
                    with pytest.raises(RuntimeError, match="sbatch failed"):
                        await scheduler.submit_job(
                            job_id="test-fail",
                            job_type="blastn",
                            parameters={"query_url": "test.fasta"}
                        )
    
    @pytest.mark.asyncio
    async def test_get_job_status_running(self):
        """Test getting status of running job"""
        scheduler = SlurmScheduler()
        
        # Mock storage returning job info
        with patch.object(scheduler, 'storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"slurm_job_id": "12345"}
            }
            
            # Mock squeue returning RUNNING status
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = Mock()
                mock_process.communicate.return_value = (b"RUNNING", b"")
                mock_process.returncode = 0
                mock_subprocess.return_value = mock_process
                
                status = await scheduler.get_job_status("test-job")
                assert status == JobStatus.RUNNING
    
    @pytest.mark.asyncio
    async def test_get_job_status_completed(self):
        """Test getting status of completed job"""
        scheduler = SlurmScheduler()
        
        # Mock storage returning job info
        with patch.object(scheduler, 'storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"slurm_job_id": "12345"}
            }
            
            # Mock squeue failing (job not in queue)
            with patch('asyncio.create_subprocess_exec') as mock_subprocess_squeue:
                mock_process = Mock()
                mock_process.communicate.return_value = (b"", b"Invalid job id specified")
                mock_process.returncode = 1
                mock_subprocess_squeue.return_value = mock_process
                
                # Mock sacct returning COMPLETED
                with patch.object(scheduler, '_check_completed_job') as mock_check:
                    mock_check.return_value = JobStatus.COMPLETED
                    
                    status = await scheduler.get_job_status("test-job")
                    assert status == JobStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_cancel_job_success(self):
        """Test successful job cancellation"""
        scheduler = SlurmScheduler()
        
        # Mock storage returning job info
        with patch.object(scheduler, 'storage') as mock_storage:
            mock_storage.get_job_info.return_value = {
                "result": {"slurm_job_id": "12345"}
            }
            mock_storage.update_job_status = Mock()
            
            # Mock successful scancel
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = Mock()
                mock_process.communicate.return_value = (b"", b"")
                mock_process.returncode = 0
                mock_subprocess.return_value = mock_process
                
                result = await scheduler.cancel_job("test-job")
                assert result is True
                mock_storage.update_job_status.assert_called_with("test-job", JobStatus.CANCELLED)
    
    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self):
        """Test cancelling job that doesn't exist"""
        scheduler = SlurmScheduler()
        
        # Mock storage returning no job info
        with patch.object(scheduler, 'storage') as mock_storage:
            mock_storage.get_job_info.return_value = None
            
            result = await scheduler.cancel_job("nonexistent-job")
            assert result is False


@pytest.mark.asyncio
async def test_scheduler_integration():
    """Integration test for scheduler system"""
    # Test that we can get a scheduler (either Celery or Slurm)
    try:
        scheduler = await get_scheduler("auto")
        assert isinstance(scheduler, BaseScheduler)
        assert scheduler.scheduler_type in [SchedulerType.CELERY, SchedulerType.SLURM]
        
        # Test that we can check availability
        is_available = await scheduler.is_available()
        assert isinstance(is_available, bool)
        
    except RuntimeError:
        # No schedulers available - this is expected in some test environments
        pytest.skip("No schedulers available for integration test")