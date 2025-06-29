# Bio-MCP Queue

⚡ **Distributed job queue system for long-running bioinformatics tasks**

Enable AI assistants to submit, monitor, and retrieve results from background bioinformatics jobs. Perfect for large datasets, long-running analyses, and multi-user environments.

## 🎯 Features

- **Async Job Processing** - Submit jobs and get results later
- **Multiple Queues** - Separate queues for different tool types
- **Scalable Workers** - Add workers as needed for parallel processing
- **S3-Compatible Storage** - MinIO for secure file handling
- **Job Monitoring** - Real-time status and progress tracking
- **REST API** - HTTP API for job management
- **Web Dashboard** - Monitor queues and workers via Flower

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐
│   MCP       │────▶│   API    │────▶│   Celery    │
│  Servers    │     │(FastAPI) │     │   Broker    │
└─────────────┘     └──────────┘     │  (Redis)    │
                           │          └─────────────┘
                           │                 │
                           ▼                 ▼
                    ┌──────────┐      ┌─────────────┐
                    │  MinIO   │      │   Workers   │
                    │ Storage  │◀─────│  (BLAST,    │
                    └──────────┘      │   BWA, etc) │
                                      └─────────────┘
```

## 🚀 Quick Start

### Local Setup (5 minutes)

```bash
# Clone and start the queue system
git clone https://github.com/bio-mcp/bio-mcp-queue.git
cd bio-mcp-queue

# Quick setup script
./setup-local.sh

# Services will be available at:
# - Queue API: http://localhost:8000
# - Job Monitor: http://localhost:5555
# - File Storage: http://localhost:9001
```

### Manual Setup

```bash
# Install dependencies
pip install -e .

# Start services with Docker Compose
docker-compose up -d

# Or start individual components
redis-server &
celery -A celery_app worker -Q blast &
python -m api &
```

## 💻 Usage

### Via MCP Servers

When MCP servers are configured with queue support:

```python
# AI Assistant interaction
User: "BLAST this large file against nr database"
AI: [calls blastn_async] → "Job submitted! ID: abc123"
AI: "I'll check the progress while you work on other things..."

# Later...
User: "How's my BLAST job?"
AI: [calls get_job_status] → "75% complete, ETA 10 minutes"

# When done...
AI: [calls get_job_result] → "Complete! Found 1,247 hits. Download link: ..."
```

### Direct API Usage

```bash
# Submit a job
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "blastn",
    "parameters": {
      "query": "/path/to/sequences.fasta",
      "database": "nt",
      "evalue": 0.001
    },
    "priority": 5
  }'

# Check job status
curl http://localhost:8000/jobs/{job_id}/status

# Get results
curl http://localhost:8000/jobs/{job_id}/result
```

### Python Client

```python
import asyncio
from bio_queue_client import QueueClient

async def main():
    client = QueueClient("http://localhost:8000")
    
    # Submit job
    job = await client.submit_job(
        job_type="blastn",
        parameters={
            "query": "sequences.fasta",
            "database": "nt"
        }
    )
    
    # Wait for completion
    while True:
        status = await client.get_status(job["job_id"])
        if status["status"] == "completed":
            break
        await asyncio.sleep(10)
    
    # Get results
    results = await client.get_results(job["job_id"])
    print(f"Results: {results['result_url']}")

asyncio.run(main())
```

## 🛠️ Configuration

### Environment Variables

```bash
# Redis Configuration
export BIO_QUEUE_REDIS_URL="redis://localhost:6379/0"
export BIO_QUEUE_RESULT_BACKEND="redis://localhost:6379/1"

# Worker Configuration
export BIO_QUEUE_TASK_TIME_LIMIT=3600          # 1 hour max
export BIO_QUEUE_TASK_SOFT_TIME_LIMIT=3300     # 55 minutes soft limit
export BIO_QUEUE_WORKER_PREFETCH_MULTIPLIER=1
export BIO_QUEUE_WORKER_MAX_TASKS_PER_CHILD=50

# Storage Configuration
export BIO_STORAGE_MINIO_ENDPOINT="localhost:9000"
export BIO_STORAGE_MINIO_ACCESS_KEY="minioadmin"
export BIO_STORAGE_MINIO_SECRET_KEY="minioadmin"
export BIO_STORAGE_BUCKET_NAME="bio-mcp-jobs"
```

### Queue Configuration

```python
# celery_app.py
app.conf.update(
    task_routes={
        'bio.tasks.blast.*': {'queue': 'blast'},
        'bio.tasks.alignment.*': {'queue': 'alignment'},
        'bio.tasks.variant.*': {'queue': 'variant'},
    },
    task_annotations={
        '*': {'rate_limit': '10/s'},
        'bio.tasks.blast.*': {'rate_limit': '5/s'},
    }
)
```

## 📊 Monitoring

### Flower Dashboard

Access the web interface at http://localhost:5555:

- **Active Workers** - See which workers are online
- **Task History** - Browse completed jobs
- **Queue Lengths** - Monitor backlog
- **Worker Stats** - CPU, memory usage per worker

### API Endpoints

```bash
# Queue statistics
curl http://localhost:8000/queues/stats

# System health
curl http://localhost:8000/health

# Job history
curl http://localhost:8000/jobs?status=completed&limit=100
```

### Logging

```bash
# Worker logs
docker-compose logs -f celery-blast

# API logs
docker-compose logs -f api

# Redis logs
docker-compose logs -f redis
```

## 🔧 Scaling

### Horizontal Scaling

```bash
# Add more BLAST workers
docker-compose up -d --scale celery-blast=8

# Add workers for different tools
docker-compose up -d --scale celery-alignment=4

# Scale across machines
docker-compose -f docker-compose.yml -f docker-compose.cluster.yml up -d
```

### Vertical Scaling

```yaml
# docker-compose.override.yml
services:
  celery-blast:
    deploy:
      resources:
        limits:
          memory: 16G
          cpus: '8'
    environment:
      - BIO_QUEUE_WORKER_CONCURRENCY=4
```

### Queue Priority

```python
# High priority jobs
await client.submit_job(
    job_type="blastn",
    parameters=params,
    priority=9  # Higher number = higher priority
)

# Bulk processing (low priority)
await client.submit_job(
    job_type="blastn",
    parameters=params,
    priority=1
)
```

## 🐳 Deployment

### Local Development

```bash
# Hot reload for development
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Production

#### Docker Swarm
```bash
docker stack deploy -c docker-compose.prod.yml bio-mcp
```

#### Kubernetes
```bash
kubectl apply -k deployment/kubernetes/
```

#### Cloud Deployment
- **AWS**: ECS Fargate + ElastiCache + S3
- **GCP**: Cloud Run + Memorystore + Cloud Storage  
- **Azure**: Container Instances + Redis Cache + Blob Storage

See [deployment guide](deployment/README.md) for details.

## 🔒 Security

### Authentication

```python
# API key authentication
headers = {"Authorization": "Bearer your-api-key"}
response = requests.post(
    "http://localhost:8000/jobs/submit",
    json=job_data,
    headers=headers
)
```

### Network Security

```yaml
# docker-compose.prod.yml
services:
  api:
    networks:
      - internal
  redis:
    networks:
      - internal
networks:
  internal:
    driver: overlay
    internal: true
```

### Data Encryption

```bash
# Enable MinIO encryption
export MINIO_SERVER_SIDE_ENCRYPTION="on"

# Use TLS for Redis
export BIO_QUEUE_REDIS_URL="rediss://localhost:6380/0"
```

## 📈 Performance Tuning

### Redis Optimization

```bash
# Increase memory limits
echo "maxmemory 4gb" >> redis.conf
echo "maxmemory-policy allkeys-lru" >> redis.conf

# Persistence settings
echo "save 900 1" >> redis.conf
echo "save 300 10" >> redis.conf
```

### Worker Optimization

```python
# Per-worker memory limits
CELERYD_MAX_MEMORY_PER_CHILD = 2000000  # 2GB

# Prefetch optimization
CELERYD_PREFETCH_MULTIPLIER = 1

# Concurrency settings
CELERYD_CONCURRENCY = 4  # Number of processes per worker
```

### Storage Optimization

```bash
# MinIO performance settings
export MINIO_STORAGE_CLASS_STANDARD="EC:4"
export MINIO_CACHE_DRIVES="/tmp/minio-cache"
export MINIO_CACHE_QUOTA=80
```

## 🧪 Development

### Adding New Task Types

1. **Create task module**:
```python
# src/bio/tasks/newtool.py
from celery_app import app

@app.task(bind=True, name='bio.tasks.newtool.run')
def run_newtool(self, job_id: str, parameters: dict):
    # Implementation here
    pass
```

2. **Update routing**:
```python
# celery_app.py
task_routes={
    'bio.tasks.newtool.*': {'queue': 'newtool'},
}
```

3. **Add API endpoint**:
```python
# api.py
@app.post("/newtool/submit")
async def submit_newtool_job(request: NewToolRequest):
    # Implementation here
    pass
```

### Testing

```bash
# Unit tests
pytest tests/test_tasks.py -v

# Integration tests
pytest tests/test_integration.py -v

# Load testing
pytest tests/test_performance.py -v
```

## 🔍 Troubleshooting

### Common Issues

**Workers not starting**
```bash
# Check Redis connection
redis-cli ping

# Check worker logs
docker-compose logs celery-blast

# Restart workers
docker-compose restart celery-blast
```

**Jobs stuck in pending**
```bash
# Check queue length
celery -A celery_app inspect active_queues

# Purge queue if needed
celery -A celery_app purge -Q blast

# Scale up workers
docker-compose up -d --scale celery-blast=4
```

**Out of disk space**
```bash
# Clean up old results
python scripts/cleanup_old_jobs.py --days 7

# Enable automatic cleanup
export BIO_STORAGE_AUTO_CLEANUP=true
export BIO_STORAGE_RETENTION_DAYS=7
```

**Memory issues**
```bash
# Monitor worker memory
docker stats

# Reduce worker concurrency
export CELERYD_CONCURRENCY=1

# Add swap space
sudo fallocate -l 8G /swapfile
sudo swapon /swapfile
```

## 📚 API Reference

### Job Management

- `POST /jobs/submit` - Submit new job
- `GET /jobs/{job_id}/status` - Get job status  
- `GET /jobs/{job_id}/result` - Get job results
- `DELETE /jobs/{job_id}` - Cancel job
- `GET /jobs` - List jobs with filters

### Queue Management

- `GET /queues/stats` - Queue statistics
- `GET /workers` - Active workers
- `POST /workers/{worker_id}/shutdown` - Shutdown worker

### System

- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## 📄 License

MIT License - see [LICENSE](LICENSE) file.

## 🆘 Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/bio-mcp/bio-mcp-queue/issues)
- 💡 **Feature Requests**: [GitHub Issues](https://github.com/bio-mcp/bio-mcp-queue/issues/new?template=feature_request.md)
- 📖 **Documentation**: [Bio-MCP Docs](https://github.com/bio-mcp/bio-mcp-docs)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/bio-mcp/bio-mcp-queue/discussions)

---

*Powering distributed bioinformatics! ⚡🧬*