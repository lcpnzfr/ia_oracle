# services/ia_oracle/Dockerfile
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install shared_lib
COPY shared_lib /app/shared_lib
RUN pip install --no-cache-dir ./shared_lib

# Install service dependencies
COPY services/ia_oracle /app/services/ia_oracle

# Fix requirements.txt for docker
RUN sed -i '/-e ..\/..\/shared_lib/d' /app/services/ia_oracle/requirements.txt
RUN sed -i '/-e git+https/d' /app/services/ia_oracle/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir ./services/ia_oracle

# Final Stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY services/ia_oracle/ia_oracle /app/ia_oracle

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Entrypoint is set in docker-compose
CMD ["python", "-m", "ia_oracle.main"]
