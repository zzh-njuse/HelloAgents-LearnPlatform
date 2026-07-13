from datetime import timedelta

from redis import Redis
from rq import Queue

from learn_platform_api.settings import Settings


def enqueue_ingestion_job(settings: Settings, job_id: str, delay_seconds: int = 0) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        queue = Queue(settings.ingestion_queue_name, connection=connection)
        if delay_seconds > 0:
            queue.enqueue_in(
                timedelta(seconds=delay_seconds),
                "learn_platform_api.workers.run_ingestion_job",
                job_id,
            )
        else:
            queue.enqueue("learn_platform_api.workers.run_ingestion_job", job_id)
    finally:
        connection.close()
