import multiprocessing
import os

workers_per_core = int(os.getenv("WORKERS_PER_CORE", "1"))
cores = multiprocessing.cpu_count()
workers = max(int(os.getenv("WEB_CONCURRENCY", cores * workers_per_core)), 2)

bind = os.getenv("BIND", "0.0.0.0:8000")
worker_class = "uvicorn.workers.UvicornWorker"
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"

# UvicornWorker manages its own async event loop; setting timeout=0 disables
# Gunicorn's synchronous heartbeat check that would otherwise kill long-running
# upload/parse tasks. keepalive covers keep-alive connections from proxies.
timeout = 0
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "65"))
