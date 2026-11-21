FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY watcher/*.py .
CMD ["python", "-u", "/app/watcher.py"]
