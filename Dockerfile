# Kaza — production image.
FROM python:3.12-slim

# Predictable, quiet Python.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

# Runtime configuration. Data lives on a mounted volume so SQLite survives
# container restarts.
ENV KAZA_ENV=production \
    DATA_DIR=/data \
    PORT=8000
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

# Container-level health probe hits the app's own health endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

# Serve with gunicorn (installed via requirements on Linux). One worker with
# threads: SQLite writes and the in-process rate limiter both assume a single
# process, and threads still give I/O concurrency. Scale to multiple workers
# only alongside PostgreSQL and a shared rate-limit store.
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60"]
