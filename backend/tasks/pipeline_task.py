"""Pipeline dispatch: in-process asyncio task by default, Celery worker when USE_CELERY=true.

Run a worker (Windows needs the solo pool):
    celery -A tasks.pipeline_task worker --loglevel=info --pool=solo
"""
import asyncio

from celery import Celery
from loguru import logger

from config import settings

celery_app = Celery(
    "factflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=200,
)

_background: set[asyncio.Task] = set()


async def _run_in_worker(request_id: str) -> None:
    from agents.orchestrator import run_pipeline
    from database import connection
    from services.event_bus import reset_bus

    reset_bus()
    await connection.init_db(null_pool=True)
    try:
        await run_pipeline(request_id)
    finally:
        await connection.close_db()


@celery_app.task(name="factflow.run_pipeline")
def run_pipeline_task(request_id: str) -> str:
    asyncio.run(_run_in_worker(request_id))
    return request_id


def dispatch(request_id: str) -> str:
    """Start the pipeline for a queued claim. Returns the execution mode used."""
    if settings.USE_CELERY:
        run_pipeline_task.delay(request_id)
        return "celery"

    from agents.orchestrator import run_pipeline

    task = asyncio.create_task(run_pipeline(request_id))
    _background.add(task)
    task.add_done_callback(_background.discard)
    logger.info(f"[{request_id}] pipeline started in-process")
    return "inprocess"
