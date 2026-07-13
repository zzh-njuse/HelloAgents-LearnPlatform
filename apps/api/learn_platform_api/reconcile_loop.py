import logging
import time

from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.jobs import reconcile_jobs
from learn_platform_api.settings import get_settings


def main() -> None:
    settings = get_settings()
    logger = logging.getLogger("learn_platform_api.reconciler")
    while True:
        try:
            with SessionLocal() as db:
                recovered = reconcile_jobs(db, settings)
            if recovered:
                logger.info("ingestion_jobs_requeued", extra={"count": recovered})
        except Exception:
            logger.exception("ingestion_reconciliation_failed")
        time.sleep(settings.ingestion_reconcile_seconds)


if __name__ == "__main__":
    main()
