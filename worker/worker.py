import logging

from rq import Worker

from app.config import settings
from app.db import engine
from app.observability import configure_observability, instrument_sqlalchemy_engine
from app.redis_conn import get_redis_connection

configure_observability(
    service_name=f"{settings.app_name}-worker",
    environment=settings.app_env,
    log_level=settings.log_level,
    enable_tracing=settings.enable_tracing,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_protocol=settings.otlp_protocol,
    seq_uri=settings.seq_uri,
)
logger = logging.getLogger(__name__)


def main():
    instrument_sqlalchemy_engine(engine)
    redis_conn = get_redis_connection()
    worker = Worker(["training"], connection=redis_conn)
    logger.info("Starting training worker.")
    worker.work(logging_level=getattr(logging, settings.log_level.upper(), logging.INFO))


if __name__ == "__main__":
    main()
