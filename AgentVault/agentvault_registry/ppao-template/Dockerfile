FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir theprotocol-orchestrator
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
EXPOSE 3100
ENTRYPOINT ["/app/entrypoint.sh"]
