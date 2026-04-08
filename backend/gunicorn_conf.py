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
