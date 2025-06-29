#!/bin/bash
# Quick setup script for local Bio-MCP queue system

set -e

echo "🧬 Setting up Bio-MCP Queue System Locally"
echo "=========================================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check available cores
CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "4")
echo "🖥️  Detected $CORES CPU cores"

# Create local data directories
echo "📁 Creating local data directories..."
mkdir -p data/{redis,minio,databases,temp}

# Detect available RAM
if command -v free > /dev/null; then
    RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
elif command -v vm_stat > /dev/null; then
    RAM_GB=$(echo "$(vm_stat | grep "Pages free" | awk '{print $3}' | sed 's/\.//')" "* 4096 / 1024 / 1024 / 1024" | bc)
else
    RAM_GB=8
fi

echo "💾 Detected ${RAM_GB}GB RAM"

# Recommend worker configuration
if [ "$RAM_GB" -lt 8 ]; then
    WORKERS=2
    echo "⚠️  Limited RAM detected. Recommending 2 workers."
elif [ "$RAM_GB" -lt 16 ]; then
    WORKERS=4
    echo "✅ Recommending 4 workers for your system."
else
    WORKERS=$((CORES > 8 ? 8 : CORES))
    echo "🚀 High-memory system. Recommending $WORKERS workers."
fi

# Create optimized docker-compose file
cat > docker-compose.override.yml << EOF
version: '3.8'
services:
  celery-blast:
    deploy:
      replicas: $WORKERS
    environment:
      - BIO_QUEUE_WORKER_CONCURRENCY=1
      - BIO_QUEUE_WORKER_MAX_MEMORY_PER_CHILD=2000000  # 2GB per worker
EOF

echo "⚙️  Created configuration for $WORKERS workers"

# Start services
echo "🚀 Starting services..."
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check service health
echo "🏥 Checking service health..."

# Check Redis
if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is ready"
else
    echo "❌ Redis failed to start"
fi

# Check MinIO
if curl -f http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "✅ MinIO is ready"
else
    echo "⚠️  MinIO is starting (may take a moment)"
fi

# Check API
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ API is ready"
else
    echo "⚠️  API is starting (may take a moment)"
fi

echo ""
echo "🎉 Bio-MCP Queue System is running locally!"
echo ""
echo "📊 Monitoring Dashboards:"
echo "   • Job Queue: http://localhost:5555"
echo "   • File Storage: http://localhost:9001"
echo "   • API Docs: http://localhost:8000/docs"
echo ""
echo "🧬 Start your MCP servers with queue support:"
echo "   cd ../bio-mcp-blast"
echo "   python -m src.main --mode queue"
echo ""
echo "💡 Tips:"
echo "   • Your data stays completely local"
echo "   • Running $WORKERS parallel workers" 
echo "   • Scale workers: docker-compose up -d --scale celery-blast=$((WORKERS*2))"
echo "   • Stop system: docker-compose down"
echo ""
echo "Happy bioinformatics! 🧬✨"