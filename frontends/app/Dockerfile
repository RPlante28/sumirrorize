FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY templates ./templates
COPY static ./static
USER nobody
EXPOSE 3500
# The container's disk is read-only: gunicorn keeps its worker heartbeat files in /dev/shm, and
# its control socket (for managing it from inside the container, which we don't use) is off.
CMD ["gunicorn", "app.main:create_app()", "--bind", "0.0.0.0:3500", "--workers", "2", "--threads", "4", \
     "--worker-tmp-dir", "/dev/shm", "--no-control-socket", "--access-logfile", "-"]
