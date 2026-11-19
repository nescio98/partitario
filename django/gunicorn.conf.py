"""Gunicorn configuration, picked up automatically from the working directory."""

import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "4"))

# Heartbeat files in memory: the container filesystem is read-only.
worker_tmp_dir = "/dev/shm"  # noqa: S108 - a fixed tmpfs path, by gunicorn's own advice

timeout = 30
graceful_timeout = 30
keepalive = 5

# Recycle workers to contain slow memory leaks; jitter avoids a stampede.
max_requests = 1000
max_requests_jitter = 100

# Only nginx can reach gunicorn (compose network), so its X-Forwarded-* are trusted.
forwarded_allow_ips = "*"

# No runtime management socket: nothing uses it and the filesystem is read-only.
control_socket_disable = True

accesslog = "-"
errorlog = "-"
