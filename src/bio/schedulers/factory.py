import os
import asyncio
import logging
from typing import Optional
from pydantic_settings import BaseSettings

from .base import BaseScheduler, SchedulerType
from .celery_scheduler import CeleryScheduler
from .slurm_scheduler import SlurmScheduler, SlurmSettings

logger = logging.getLogger(__name__)


class SchedulerSettings(BaseSettings):
    """Global scheduler settings"""
    scheduler_type: str = "auto"  # auto, celery, slurm
    scheduler_fallback: bool = True  # Fall back to Celery if preferred scheduler unavailable
    
    class Config:
        env_prefix = "BIO_MCP_"


async def detect_available_schedulers() -> dict:
    """Detect which schedulers are available"""
    available = {}
    
    # Check Celery
    try:
        celery_scheduler = CeleryScheduler()
        available["celery"] = await celery_scheduler.is_available()
    except Exception as e:
        logger.debug(f"Celery not available: {e}")
        available["celery"] = False
    
    # Check Slurm
    try:
        slurm_scheduler = SlurmScheduler()
        available["slurm"] = await slurm_scheduler.is_available()
    except Exception as e:
        logger.debug(f"Slurm not available: {e}")
        available["slurm"] = False
    
    return available


async def get_scheduler(
    scheduler_type: Optional[str] = None,
    settings: Optional[SchedulerSettings] = None
) -> BaseScheduler:
    """
    Get the appropriate scheduler based on configuration and availability
    
    Args:
        scheduler_type: Override scheduler type ("auto", "celery", "slurm")
        settings: Optional settings override
    
    Returns:
        Configured scheduler instance
    
    Raises:
        RuntimeError: If no scheduler is available
    """
    if settings is None:
        settings = SchedulerSettings()
    
    requested_type = scheduler_type or settings.scheduler_type
    
    # Detect available schedulers
    available = await detect_available_schedulers()
    
    logger.info(f"Available schedulers: {available}")
    
    # Auto-selection logic
    if requested_type == "auto":
        # Prefer Slurm if available, fall back to Celery
        if available.get("slurm", False):
            logger.info("Auto-selected Slurm scheduler")
            return SlurmScheduler()
        elif available.get("celery", False):
            logger.info("Auto-selected Celery scheduler")
            return CeleryScheduler()
        else:
            raise RuntimeError("No schedulers available. Please configure Celery or Slurm.")
    
    # Explicit scheduler selection
    elif requested_type == "slurm":
        if available.get("slurm", False):
            logger.info("Using Slurm scheduler")
            return SlurmScheduler()
        elif settings.scheduler_fallback and available.get("celery", False):
            logger.warning("Slurm not available, falling back to Celery")
            return CeleryScheduler()
        else:
            raise RuntimeError("Slurm scheduler not available and fallback disabled")
    
    elif requested_type == "celery":
        if available.get("celery", False):
            logger.info("Using Celery scheduler")
            return CeleryScheduler()
        elif settings.scheduler_fallback and available.get("slurm", False):
            logger.warning("Celery not available, falling back to Slurm")
            return SlurmScheduler()
        else:
            raise RuntimeError("Celery scheduler not available and fallback disabled")
    
    else:
        raise ValueError(f"Unknown scheduler type: {requested_type}")


def get_scheduler_config_status() -> dict:
    """Get current scheduler configuration status"""
    settings = SchedulerSettings()
    
    status = {
        "requested_scheduler": settings.scheduler_type,
        "fallback_enabled": settings.scheduler_fallback,
        "slurm_configured": bool(os.environ.get("BIO_SLURM_PARTITION") or 
                                os.environ.get("BIO_SLURM_ACCOUNT")),
        "celery_configured": bool(os.environ.get("BIO_QUEUE_REDIS_URL"))
    }
    
    return status


async def validate_scheduler_config(scheduler_type: str = "auto") -> dict:
    """
    Validate scheduler configuration and provide setup guidance
    
    Returns:
        Dictionary with validation results and setup instructions
    """
    available = await detect_available_schedulers()
    config_status = get_scheduler_config_status()
    
    validation = {
        "valid": False,
        "available_schedulers": available,
        "config_status": config_status,
        "recommendations": [],
        "missing_config": []
    }
    
    if scheduler_type == "auto" or scheduler_type == "slurm":
        if available.get("slurm", False):
            validation["valid"] = True
            if not config_status["slurm_configured"]:
                validation["recommendations"].append(
                    "Consider setting BIO_SLURM_PARTITION and BIO_SLURM_ACCOUNT for better defaults"
                )
        else:
            validation["missing_config"].append("Slurm not available (sbatch command not found)")
    
    if scheduler_type == "auto" or scheduler_type == "celery":
        if available.get("celery", False):
            validation["valid"] = True
        else:
            validation["missing_config"].append("Celery not available (no active workers)")
            if not config_status["celery_configured"]:
                validation["missing_config"].append("Set BIO_QUEUE_REDIS_URL for Celery")
    
    if not validation["valid"]:
        validation["recommendations"].extend([
            "For Slurm: Ensure sbatch is in PATH and optionally set BIO_SLURM_PARTITION",
            "For Celery: Start Redis and Celery workers, set BIO_QUEUE_REDIS_URL"
        ])
    
    return validation