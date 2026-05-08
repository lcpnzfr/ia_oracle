# services/ia_oracle/Dockerfile
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# 2. Internal Libs (Cached)
COPY cryptor/requirements.txt /app/cryptor_reqs.txt
RUN sed -i '/git+https/d; /MetaTrader5/d; /metatrader5/d; /shared_lib/d; /cryptor/d' /app/cryptor_reqs.txt
RUN pip install --no-cache-dir -r /app/cryptor_reqs.txt
COPY cryptor /app/cryptor
RUN pip install --no-cache-dir ./cryptor

COPY shared_lib/requirements.txt /app/shared_lib_reqs.txt
RUN sed -i '/git+https/d; /MetaTrader5/d; /metatrader5/d; /shared_lib/d; /cryptor/d' /app/shared_lib_reqs.txt
RUN pip install --no-cache-dir -r /app/shared_lib_reqs.txt
COPY shared_lib /app/shared_lib
RUN pip install --no-cache-dir ./shared_lib

# 3. Service Dependencies (Cached)
COPY services/ia_oracle/requirements.txt /app/service_reqs.txt
RUN sed -i '/git+https/d; /MetaTrader5/d; /metatrader5/d; /shared_lib/d; /cryptor/d' /app/service_reqs.txt
RUN pip install --no-cache-dir -r /app/service_reqs.txt

# Final Stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 4. App Code (Instant Updates)
COPY services/ia_oracle/ia_oracle /app/ia_oracle

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Entrypoint is set in docker-compose
CMD ["python", "-m", "ia_oracle.main"]
