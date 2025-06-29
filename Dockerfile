FROM python:3.11

# Install bioinformatics tools
RUN apt-get update && apt-get install -y \
    ncbi-blast+ \
    samtools \
    bwa \
    bcftools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install -e .

# Add FastAPI dependencies
RUN pip install fastapi uvicorn

# Copy source code
COPY src/ ./src/

# Create non-root user
RUN useradd -m -u 1000 celery && \
    chown -R celery:celery /app

USER celery

# Default to API, but can be overridden
CMD ["python", "-m", "api"]