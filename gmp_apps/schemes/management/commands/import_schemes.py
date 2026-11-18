from django.core.management.base import BaseCommand, CommandError

from gmp_apps.schemes.sync.runner import SchemeSyncRunner, SyncBusyError


class Command(BaseCommand):
    help = (
        'One-time bulk import (and manual re-sync) of government schemes from the approved sitemap. '
        'New schemes arrive as "pending review". Safe to run repeatedly: no duplicates.'
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('--limit', type=int, default=None, help='Fetch at most this many pages (try 10 first)')
        parser.add_argument('--force', action='store_true', help='Re-fetch pages even if the sitemap lastmod is unchanged')

    def handle(self, *args: object, **options: object) -> None:
        runner = SchemeSyncRunner(trigger='command', force=bool(options['force']), limit=options['limit'])
        try:
            run = runner.run()
        except SyncBusyError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f'Run #{run.run_id} {run.status}: sitemap URLs {run.sitemap_urls}, scheme URLs {run.scheme_urls}, '
            f'fetched {run.fetched}, images {run.images_downloaded}, documents {run.documents_downloaded}, created {run.created}, updated {run.updated}, unchanged {run.unchanged}, '
            f'excluded {run.skipped_excluded}, edited-by-admin {run.skipped_edited}, invalid {run.skipped_invalid}, '
            f'errors {run.errors}, media pending {run.media_pending}',
        )
        if run.error_summary:
            self.stdout.write(run.error_summary)
        if run.status == 'failed':
            raise CommandError('Sync failed (see run log above and in the admin)')
