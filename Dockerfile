FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY server.py .

# Storage directory (writable at runtime)
RUN mkdir -p /app/workflow_storage/files

EXPOSE 9090

CMD ["python", "server.py"]
