# Bio-MCP Queue System

Distributed job queue system for long-running bioinformatics tasks with support for both Celery and Slurm schedulers.

## Overview

This system provides:
- **Dual scheduler support** - Celery for development/containers, Slurm for HPC clusters
- **Auto-detection** and fallback between schedulers
- **Async job submission** for long-running bioinformatics tasks
- **S3-compatible storage** with MinIO for input/output files
- **REST API** for job submission and monitoring
- **Interactive configuration** via MCP tools
- **Multiple queues** for different tool types (BLAST, alignment, etc.)

## Architecture

### Scheduler Support
The system supports two job schedulers with automatic detection and fallback:

**Celery Mode (Development/Containers):**
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   MCP       │────▶│     API      │────▶│   Celery    │
│  Servers    │     │ (Scheduler   │     │   Broker    │
└─────────────┘     │ Abstraction) │     │   (Redis)   │
                    └──────────────┘     └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────┐         ┌─────────────┐
                    │  MinIO   │         │   Workers   │
                    │ Storage  │◀────────│  (BLAST,    │
                    └──────────┘         │   BWA, etc) │
                                         └─────────────┘
```

**Slurm Mode (HPC Clusters):**
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   MCP       │────▶│     API      │────▶│    Slurm    │
│  Servers    │     │ (Scheduler   │     │   Cluster   │
└─────────────┘     │ Abstraction) │     │   (sbatch)  │
                    └──────────────┘     └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────┐         ┌─────────────┐
                    │  Shared  │         │ Compute     │
                    │ Storage  │◀────────│ Nodes       │
                    │(NFS/GPFS)│         │ (srun jobs) │
                    └──────────┘         └─────────────┘
```

## Quick Start

### Option 1: Auto-Setup Scripts

**For Celery (Local Development):**
```bash
cd bio-mcp-queue
./scripts/setup-celery.sh
```

**For Slurm (HPC Clusters):**
```bash
cd bio-mcp-queue
./scripts/setup-slurm.sh
```

### Option 2: Manual Setup

**Celery Mode:**
```bash
# Start Redis and MinIO
docker-compose up -d redis minio

# Start Celery workers
celery -A src.celery_app worker --loglevel=info

# Start API server
python -m src.api
```

**Slurm Mode:**
```bash
# Set environment variables
export BIO_MCP_SCHEDULER_TYPE=slurm
export BIO_SLURM_PARTITION=compute
export BIO_SLURM_ACCOUNT=mylab

# Start API server (jobs will be submitted to Slurm)
python -m src.api
```

### Option 3: Docker (Celery Only)
```bash
cd bio-mcp-queue
docker-compose up -d
```

**Access services:**
- API: http://localhost:8000/docs
- MinIO Console: http://localhost:9001 (minioadmin/minioadmin)
- Flower (Celery monitor): http://localhost:5555

**Submit a job via API:**
```bash
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "blastn",
    "parameters": {
      "query_url": "s3://bucket/sequences.fasta",
      "database": "nr",
      "evalue": 0.001,
      "resources": {
        "cpus": 4,
        "memory_mb": 8192,
        "walltime_minutes": 60
      }
    }
  }'
```

## Scheduler Configuration

### Interactive Configuration via MCP Tools

The system includes MCP tools for interactive scheduler setup:

```bash
# Run the MCP configuration server
python -m src.bio.mcp_tools
```

Available MCP tools:
- `check_scheduler_status` - Check current scheduler availability
- `configure_scheduler` - Interactive setup wizard  
- `set_slurm_config` - Configure Slurm settings
- `test_scheduler` - Submit a test job
- `save_scheduler_config` - Save configuration to file

### Environment Variables

**Scheduler Selection:**
```bash
# Preferred scheduler: auto, celery, slurm
BIO_MCP_SCHEDULER_TYPE=auto

# Enable fallback to other scheduler if unavailable
BIO_MCP_SCHEDULER_FALLBACK=true
```

**Slurm Configuration:**
```bash
BIO_SLURM_PARTITION=compute         # Optional: default partition
BIO_SLURM_ACCOUNT=mylab            # Optional: account to charge
BIO_SLURM_QOS=normal               # Optional: quality of service
BIO_SLURM_WORK_DIR=/scratch/jobs   # Working directory
BIO_SLURM_MODULES=blast:samtools   # Modules to load
```

**Celery Configuration:**
```bash
BIO_QUEUE_REDIS_URL=redis://localhost:6379/0
BIO_QUEUE_TASK_TIME_LIMIT=3600
BIO_QUEUE_WORKER_PREFETCH_MULTIPLIER=1
```

### Configuration Files

Copy and customize the example configuration:
```bash
cp config/scheduler-examples.env .env
# Edit .env with your settings
source .env
```

## Integration with MCP Servers

The BLAST MCP server includes async extensions:

```python
from src.async_extensions import AsyncBlastServer

# Use the async-enabled server
server = AsyncBlastServer(queue_url="http://localhost:8000")
```

This adds tools:
- `blastn_async` - Submit BLAST job to queue
- `get_job_status` - Check job progress
- `get_job_result` - Retrieve completed results

Jobs will automatically use the configured scheduler (Celery or Slurm).

## Worker Configuration

### Adding More Workers

Scale specific queues:
```bash
docker-compose up -d --scale celery-blast=4
```

### Custom Worker Types

Add new worker types in docker-compose.yml:
```yaml
celery-samtools:
  build: .
  command: celery -A celery_app worker -Q samtools -l info
  # ... rest of config
```

## Storage

Files are stored in MinIO with structure:
```
bio-mcp-jobs/
├── inputs/
│   └── {job_id}/
├── results/
│   └── {job_id}/
└── databases/
    └── {job_id}/
```

Results are available via presigned URLs for 7 days.

## Monitoring

### Flower Dashboard
View real-time worker status, task history, and queue lengths at http://localhost:5555

### API Endpoints
- `GET /queues/stats` - Queue statistics
- `GET /jobs/{job_id}/status` - Individual job status

## Production Deployment

### Kubernetes
```bash
kubectl apply -f deployment/kubernetes/
```

### AWS ECS
Use the provided task definitions with:
- Amazon ElastiCache for Redis
- Amazon S3 instead of MinIO
- Auto-scaling for workers

## Environment Variables

### Scheduler Configuration
- `BIO_MCP_SCHEDULER_TYPE` - Scheduler type: `auto`, `celery`, `slurm`
- `BIO_MCP_SCHEDULER_FALLBACK` - Enable fallback: `true`, `false`

### Slurm Settings
- `BIO_SLURM_PARTITION` - Default Slurm partition (optional)
- `BIO_SLURM_ACCOUNT` - Account to charge jobs to (optional)
- `BIO_SLURM_QOS` - Quality of Service (optional)
- `BIO_SLURM_WORK_DIR` - Working directory for job files
- `BIO_SLURM_MODULES` - Colon-separated list of modules to load
- `BIO_SLURM_DEFAULT_CPUS` - Default CPU count per job
- `BIO_SLURM_DEFAULT_MEMORY_MB` - Default memory per job (MB)
- `BIO_SLURM_DEFAULT_WALLTIME_MINUTES` - Default time limit per job

### Celery/Queue System  
- `BIO_QUEUE_REDIS_URL` - Redis connection URL
- `BIO_QUEUE_TASK_TIME_LIMIT` - Max task runtime (seconds)
- `BIO_QUEUE_WORKER_PREFETCH_MULTIPLIER` - Worker prefetch settings
- `BIO_QUEUE_WORKER_MAX_TASKS_PER_CHILD` - Max tasks per worker process

### Storage
- `BIO_STORAGE_MINIO_ENDPOINT` - MinIO endpoint
- `BIO_STORAGE_MINIO_ACCESS_KEY` - Access key
- `BIO_STORAGE_MINIO_SECRET_KEY` - Secret key
- `BIO_STORAGE_REDIS_URL` - Redis URL for job metadata

## Security Considerations

1. **Authentication**: Add API key authentication for production
2. **Network**: Isolate workers from public internet
3. **Storage**: Enable MinIO encryption and access policies
4. **Secrets**: Use proper secret management (not hardcoded)

## Extending

To add a new bioinformatics tool:

1. Create task in `src/bio/tasks/{tool_name}.py`
2. Add worker queue in docker-compose.yml
3. Update API to handle new job type
4. Extend MCP server with async support

## License

MIT