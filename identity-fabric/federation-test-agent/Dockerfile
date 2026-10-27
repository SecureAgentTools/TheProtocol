FROM python:3.11-slim

LABEL maintainer="TheProtocol Federation Test Suite"
LABEL description="Federation test agent — onboards itself + IRONHAND mTLS for sandbox federation tests"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY agent.py .

RUN useradd -m -u 1500 fedagent && \
    mkdir -p /var/lib/agent && \
    chown -R fedagent:fedagent /app /var/lib/agent

USER fedagent

ENV PYTHONUNBUFFERED=1

CMD ["python", "agent.py"]
