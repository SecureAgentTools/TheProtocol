FROM python:3.11-slim

# Metadata
LABEL maintainer="AgentVault Team"
LABEL description="AgentVault Sample SPIFFE Workload"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app_simple.py app.py

# Create non-root user for security
RUN useradd -m -u 1000 agentvault && \
    chown -R agentvault:agentvault /app

# Switch to non-root user
USER agentvault

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV SPIFFE_ENDPOINT_SOCKET=unix:///spire-agent-socket/agent.sock

# Default command
CMD ["python", "app.py"]
