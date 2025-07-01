#!/bin/bash
# Setup script for Celery scheduler configuration

set -e

echo "🚀 Bio-MCP Queue Celery Setup"
echo "=============================="

# Check dependencies
echo "🔍 Checking dependencies..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 not found"
    exit 1
fi
echo "✅ Python found: $(python3 --version)"

# Check Redis
if ! command -v redis-server &> /dev/null; then
    echo "⚠️  Redis server not found. Installing..."
    
    if command -v brew &> /dev/null; then
        echo "Installing Redis via Homebrew..."
        brew install redis
    elif command -v apt &> /dev/null; then
        echo "Installing Redis via apt..."
        sudo apt update && sudo apt install -y redis-server
    elif command -v yum &> /dev/null; then
        echo "Installing Redis via yum..."
        sudo yum install -y redis
    else
        echo "❌ Cannot install Redis automatically. Please install manually:"
        echo "   macOS: brew install redis"
        echo "   Ubuntu/Debian: sudo apt install redis-server"
        echo "   CentOS/RHEL: sudo yum install redis"
        exit 1
    fi
fi

echo "✅ Redis found: $(redis-server --version | head -1)"

# Check if Redis is running
if ! redis-cli ping &> /dev/null; then
    echo "🚀 Starting Redis server..."
    
    # Try to start Redis
    if command -v brew &> /dev/null && brew services list | grep redis &> /dev/null; then
        brew services start redis
    elif systemctl is-active --quiet redis-server; then
        echo "Redis is already running"
    elif systemctl is-enabled --quiet redis-server; then
        sudo systemctl start redis-server
    else
        echo "Starting Redis in background..."
        redis-server --daemonize yes
    fi
    
    # Wait for Redis to start
    sleep 2
    
    if redis-cli ping &> /dev/null; then
        echo "✅ Redis is now running"
    else
        echo "❌ Failed to start Redis. Please start it manually:"
        echo "   redis-server --daemonize yes"
        exit 1
    fi
else
    echo "✅ Redis is already running"
fi

# Interactive configuration
echo ""
echo "🔧 Configuration Setup"
echo "====================="

# Get Redis URL
DEFAULT_REDIS_URL="redis://localhost:6379/0"
read -p "Redis URL [$DEFAULT_REDIS_URL]: " REDIS_URL
REDIS_URL=${REDIS_URL:-$DEFAULT_REDIS_URL}

# Test Redis connection
if ! redis-cli -u "$REDIS_URL" ping &> /dev/null; then
    echo "❌ Cannot connect to Redis at $REDIS_URL"
    exit 1
fi
echo "✅ Redis connection successful"

# Resource configuration
echo ""
echo "📊 Resource Configuration"
echo "========================"

read -p "Task time limit (seconds) [3600]: " TIME_LIMIT
read -p "Worker prefetch multiplier [1]: " PREFETCH
read -p "Max tasks per worker child [50]: " MAX_TASKS

TIME_LIMIT=${TIME_LIMIT:-3600}
PREFETCH=${PREFETCH:-1}
MAX_TASKS=${MAX_TASKS:-50}

# Generate configuration
CONFIG_FILE="bio-mcp-celery.env"
echo ""
echo "💾 Generating configuration file: $CONFIG_FILE"

cat > "$CONFIG_FILE" << EOF
# Bio-MCP Queue Celery Configuration
# Generated on $(date)

# Scheduler selection
BIO_MCP_SCHEDULER_TYPE=celery
BIO_MCP_SCHEDULER_FALLBACK=true

# Celery broker and result backend
BIO_QUEUE_REDIS_URL=$REDIS_URL
BIO_QUEUE_RESULT_BACKEND=${REDIS_URL%/*}/1

# Task execution limits
BIO_QUEUE_TASK_TIME_LIMIT=$TIME_LIMIT
BIO_QUEUE_TASK_SOFT_TIME_LIMIT=$((TIME_LIMIT - 300))

# Worker configuration
BIO_QUEUE_WORKER_PREFETCH_MULTIPLIER=$PREFETCH
BIO_QUEUE_WORKER_MAX_TASKS_PER_CHILD=$MAX_TASKS

# Storage configuration
BIO_STORAGE_REDIS_URL=${REDIS_URL%/*}/2
BIO_STORAGE_MINIO_ENDPOINT=localhost:9000
BIO_STORAGE_MINIO_ACCESS_KEY=minioadmin
BIO_STORAGE_MINIO_SECRET_KEY=minioadmin
BIO_STORAGE_MINIO_SECURE=false
BIO_STORAGE_BUCKET_NAME=bio-mcp-jobs
EOF

echo "✅ Configuration saved to $CONFIG_FILE"

# Install Python dependencies
echo ""
echo "📦 Installing Python Dependencies"
echo "================================="

if [[ -f "pyproject.toml" ]]; then
    echo "Installing bio-mcp-queue package..."
    python3 -m pip install -e .
else
    echo "Installing core dependencies..."
    python3 -m pip install celery[redis] redis pydantic pydantic-settings minio fastapi uvicorn
fi

# Source configuration
export $(grep -v '^#' "$CONFIG_FILE" | xargs)

# Test Celery
echo ""
echo "🧪 Testing Celery Configuration"
echo "==============================="

# Check if we're in the right directory
if [[ ! -f "src/celery_app.py" ]]; then
    echo "⚠️  Not in bio-mcp-queue directory. Skipping Celery test."
else
    echo "Testing Celery connection..."
    
    # Test basic Celery functionality
    if python3 -c "
import sys
sys.path.append('src')
from celery_app import app
result = app.control.inspect().stats()
print('✅ Celery connection successful')
" 2>/dev/null; then
        echo "✅ Celery configuration is working"
    else
        echo "⚠️  Celery test failed (workers not running yet)"
    fi
fi

# Setup MinIO for local development
echo ""
echo "🗄️  Storage Setup"
echo "================"

if command -v docker &> /dev/null; then
    echo "Setting up MinIO with Docker..."
    
    # Check if MinIO container is already running
    if ! docker ps | grep minio &> /dev/null; then
        echo "Starting MinIO container..."
        docker run -d \
            --name bio-mcp-minio \
            -p 9000:9000 \
            -p 9001:9001 \
            -e MINIO_ROOT_USER=minioadmin \
            -e MINIO_ROOT_PASSWORD=minioadmin \
            minio/minio server /data --console-address ":9001"
        
        echo "✅ MinIO started at http://localhost:9001"
        echo "   Username: minioadmin"
        echo "   Password: minioadmin"
    else
        echo "✅ MinIO is already running"
    fi
else
    echo "⚠️  Docker not found. MinIO setup skipped."
    echo "   Install Docker or configure external object storage"
fi

echo ""
echo "🎉 Setup Complete!"
echo "=================="
echo ""
echo "To use this configuration:"
echo "  source $CONFIG_FILE"
echo ""
echo "Start Celery workers:"
echo "  celery -A src.celery_app worker --loglevel=info"
echo ""
echo "Start the API server:"
echo "  python -m src.api"
echo ""
echo "Monitor jobs (optional):"
echo "  celery -A src.celery_app flower"
echo ""
echo "Web interfaces:"
echo "  - API: http://localhost:8000"
echo "  - MinIO: http://localhost:9001"
echo "  - Flower (if installed): http://localhost:5555"