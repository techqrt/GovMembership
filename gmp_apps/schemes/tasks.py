import logging
from typing import Any

from celery import shared_task

from gmp_apps.schemes.sync.runner import SchemeSyncRunner, SyncBusyError

logger = logging.getLogger(__name__)


@shared_task(name='gmp_apps.schemes.tasks.sync_schemes', soft_time_limit=7200, time_limit=7500)
def sync_schemes() -> dict[str, Any]:
    """Daily Celery Beat job: sync the approved sitemap. Never starts a second run on top of one."""
    try:
        run = SchemeSyncRunner(trigger='beat').run()
    except SyncBusyError:
        logger.warning('Scheme sync skipped: another run is in progress')
        return {'skipped': 'busy'}
    summary = {
        'status': run.status, 'created': run.created, 'updated': run.updated, 'unchanged': run.unchanged,
        'errors': run.errors,
    }
    logger.info('Scheme sync finished: %s', summary)
    return summary
