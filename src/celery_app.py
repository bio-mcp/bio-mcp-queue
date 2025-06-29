from celery import Celery
from celery.signals import task_prerun, task_postrun, task_failure
from pydantic_settings import BaseSettings
import logging
import os

logger = logging.getLogger(__name__)


class QueueSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    task_time_limit: int = 3600  # 1 hour
    task_soft_time_limit: int = 3300  # 55 minutes
    worker_prefetch_multiplier: int = 1
    worker_max_tasks_per_child: int = 50
    
    class Config:
        env_prefix = "BIO_QUEUE_"


settings = QueueSettings()

# Create Celery app
app = Celery('bio-mcp-queue')

app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.result_backend,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_time_limit=settings.task_time_limit,
    task_soft_time_limit=settings.task_soft_time_limit,
    worker_prefetch_multiplier=settings.worker_prefetch_multiplier,
    worker_max_tasks_per_child=settings.worker_max_tasks_per_child,
    task_routes={
        'bio.tasks.blast.*': {'queue': 'blast'},
        'bio.tasks.alignment.*': {'queue': 'alignment'},
        'bio.tasks.variant.*': {'queue': 'variant'},
        'bio.tasks.assembly.*': {'queue': 'assembly'},
    },
    task_annotations={
        '*': {'rate_limit': '10/s'},
        'bio.tasks.blast.*': {'rate_limit': '5/s'},
    }
)

# Task lifecycle logging
@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kw):
    logger.info(f"Task {task.name} [{task_id}] starting")

@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kw):
    logger.info(f"Task {task.name} [{task_id}] completed with state: {state}")

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **kw):
    logger.error(f"Task {sender.name} [{task_id}] failed: {exception}")

# Auto-discover tasks
app.autodiscover_tasks(['bio.tasks'])