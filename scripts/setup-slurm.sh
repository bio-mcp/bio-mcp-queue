#!/bin/bash
# Setup script for Slurm scheduler configuration

set -e

echo "🚀 Bio-MCP Queue Slurm Setup"
echo "============================"

# Check if Slurm is available
if ! command -v sbatch &> /dev/null; then
    echo "❌ Error: Slurm not found. Please install Slurm first."
    echo "   On Ubuntu/Debian: sudo apt install slurm-client"
    echo "   On CentOS/RHEL: sudo yum install slurm"
    exit 1
fi

echo "✅ Slurm found: $(which sbatch)"

# Check available partitions
echo ""
echo "📋 Available Slurm partitions:"
if sinfo &> /dev/null; then
    sinfo -h -o "%P %a %l %N" | head -10
else
    echo "   Unable to query partitions (may need cluster access)"
fi

# Check available accounts
echo ""
echo "💳 Available accounts:"
if sacctmgr show account -n &> /dev/null; then
    sacctmgr show account -n | head -10
else
    echo "   Unable to query accounts (may need admin access)"
fi

# Interactive configuration
echo ""
echo "🔧 Configuration Setup"
echo "====================="

# Get current user's default account
DEFAULT_ACCOUNT=""
if sacctmgr show user $USER -n &> /dev/null; then
    DEFAULT_ACCOUNT=$(sacctmgr show user $USER -n | awk '{print $2}' | head -1)
fi

# Prompt for configuration
read -p "Enter Slurm partition (press Enter for cluster default): " PARTITION
read -p "Enter Slurm account${DEFAULT_ACCOUNT:+ [default: $DEFAULT_ACCOUNT]}: " ACCOUNT
read -p "Enter QoS (press Enter for default): " QOS
read -p "Enter working directory [default: /tmp/bio-mcp-jobs]: " WORK_DIR

# Set defaults
ACCOUNT=${ACCOUNT:-$DEFAULT_ACCOUNT}
WORK_DIR=${WORK_DIR:-/tmp/bio-mcp-jobs}

# Modules setup
echo ""
echo "🧩 Module Configuration"
echo "======================"
echo "Enter modules to load (e.g., blast/2.13.0 samtools/1.17)"
echo "One per line, press Enter on empty line to finish:"

MODULES=()
while IFS= read -r -p "Module: " module; do
    [[ -z "$module" ]] && break
    MODULES+=("$module")
done

# Create work directory
echo ""
echo "📁 Creating work directory: $WORK_DIR"
if [[ ! -d "$WORK_DIR" ]]; then
    mkdir -p "$WORK_DIR" 2>/dev/null || {
        echo "❌ Cannot create $WORK_DIR"
        echo "   Please create it manually or choose a different path"
        exit 1
    }
fi

# Generate configuration
CONFIG_FILE="bio-mcp-slurm.env"
echo ""
echo "💾 Generating configuration file: $CONFIG_FILE"

cat > "$CONFIG_FILE" << EOF
# Bio-MCP Queue Slurm Configuration
# Generated on $(date)

# Scheduler selection
BIO_MCP_SCHEDULER_TYPE=slurm
BIO_MCP_SCHEDULER_FALLBACK=true

# Slurm settings
EOF

if [[ -n "$PARTITION" ]]; then
    echo "BIO_SLURM_PARTITION=$PARTITION" >> "$CONFIG_FILE"
fi

if [[ -n "$ACCOUNT" ]]; then
    echo "BIO_SLURM_ACCOUNT=$ACCOUNT" >> "$CONFIG_FILE"
fi

if [[ -n "$QOS" ]]; then
    echo "BIO_SLURM_QOS=$QOS" >> "$CONFIG_FILE"
fi

echo "BIO_SLURM_WORK_DIR=$WORK_DIR" >> "$CONFIG_FILE"

if [[ ${#MODULES[@]} -gt 0 ]]; then
    MODULES_STR=$(IFS=:; echo "${MODULES[*]}")
    echo "BIO_SLURM_MODULES=$MODULES_STR" >> "$CONFIG_FILE"
fi

cat >> "$CONFIG_FILE" << EOF

# Default resource limits
BIO_SLURM_DEFAULT_CPUS=1
BIO_SLURM_DEFAULT_MEMORY_MB=1024
BIO_SLURM_DEFAULT_WALLTIME_MINUTES=60
EOF

echo "✅ Configuration saved to $CONFIG_FILE"

# Test configuration
echo ""
echo "🧪 Testing Configuration"
echo "======================="

# Source the config
export $(grep -v '^#' "$CONFIG_FILE" | xargs)

# Test sbatch
echo "Testing job submission..."
TEST_SCRIPT=$(mktemp)
cat > "$TEST_SCRIPT" << 'EOF'
#!/bin/bash
#SBATCH --job-name=bio-mcp-test
#SBATCH --time=1
#SBATCH --output=/dev/null

echo "Bio-MCP test job completed successfully"
EOF

# Build sbatch command
SBATCH_CMD="sbatch"
[[ -n "$PARTITION" ]] && SBATCH_CMD+=" --partition=$PARTITION"
[[ -n "$ACCOUNT" ]] && SBATCH_CMD+=" --account=$ACCOUNT"
[[ -n "$QOS" ]] && SBATCH_CMD+=" --qos=$QOS"

if $SBATCH_CMD "$TEST_SCRIPT" &> /dev/null; then
    echo "✅ Test job submitted successfully"
else
    echo "⚠️  Test job submission failed (this may be normal if you don't have access)"
fi

rm -f "$TEST_SCRIPT"

echo ""
echo "🎉 Setup Complete!"
echo "=================="
echo ""
echo "To use this configuration:"
echo "  source $CONFIG_FILE"
echo ""
echo "Or add to your shell profile:"
echo "  echo 'source $(pwd)/$CONFIG_FILE' >> ~/.bashrc"
echo ""
echo "Then start the Bio-MCP queue server:"
echo "  cd /path/to/bio-mcp-queue"
echo "  python -m src.api"