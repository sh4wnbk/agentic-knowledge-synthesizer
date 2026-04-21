FROM python:3.12-slim

WORKDIR /app

# System deps required by chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first.
# Default torch install pulls the CUDA build (~2 GB). CPU-only is ~200 MB.
# sentence-transformers detects torch already present and uses it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

EXPOSE 8080

CMD uvicorn orchestrate.skill_server:app --host 0.0.0.0 --port ${PORT:-8080}
