from django.core.management.base import BaseCommand, CommandError

from gmp_apps.schemes.media_check import find_problems, requeue_media
from gmp_apps.schemes.models import Scheme, SchemeDocument, SchemeImage
from gmp_apps.schemes.sync.runner import SchemeSyncRunner, SyncBusyError

SHOW_DEFAULT = 30


class Command(BaseCommand):
    help = (
        'Verify that every imported scheme has the pictures and PDFs its page promised and that the stored '
        'files exist. Exit code 1 when something is wrong. --repair fixes what can be fixed by syncing again.'
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('--repair', action='store_true', help='Re-sync the affected schemes (fetches their pages and media again)')
        parser.add_argument('--limit', type=int, default=None, help='With --repair: fetch at most this many pages in this run')
        parser.add_argument('--show', type=int, default=SHOW_DEFAULT, help='How many problem schemes to list')

    def handle(self, *args: object, **options: object) -> None:
        problems = find_problems()
        self._report(problems, int(options['show']))
        if problems and options['repair']:
            self._repair(problems, options['limit'])
            problems = find_problems()
            self.stdout.write('\nAfter repair:')
            self._report(problems, int(options['show']))
        if problems:
            raise CommandError(f'{len(problems)} scheme(s) have missing or unverified pictures/PDFs')

    def _report(self, problems: dict[int, list[str]], show: int) -> None:
        source_schemes = Scheme.objects.filter(source_url__isnull=False, is_manual=False, locally_edited=False).count()
        pictures, documents = SchemeImage.objects.count(), SchemeDocument.objects.count()
        if not problems:
            self.stdout.write(f'OK: {source_schemes} imported schemes verified; {pictures} pictures and {documents} PDFs, all files present.')
            return
        self.stdout.write(f'PROBLEMS: {len(problems)} of {source_schemes} imported schemes ({pictures} pictures, {documents} PDFs stored).')
        titles = dict(Scheme.objects.filter(pk__in=list(problems)[:show]).values_list('pk', 'title'))
        for scheme_id in list(problems)[:show]:
            self.stdout.write(f'  #{scheme_id} {titles.get(scheme_id, "?")[:50]}: ' + '; '.join(problems[scheme_id][:3]))
        if len(problems) > show:
            self.stdout.write(f'  ... and {len(problems) - show} more (use --show)')

    def _repair(self, problems: dict[int, list[str]], limit: int | None) -> None:
        owned, removed = requeue_media(problems)
        self.stdout.write(f'\nRepairing {len(owned)} scheme(s) ({removed} broken file record(s) removed); syncing...')
        skipped = len(problems) - len(owned)
        if skipped:
            self.stdout.write(f'  {skipped} scheme(s) are owned by an admin (edited or manual): re-upload their files in the admin.')
        try:
            run = SchemeSyncRunner(trigger='command', limit=limit).run()
        except SyncBusyError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f'Run #{run.run_id} {run.status}: fetched {run.fetched}, images {run.images_downloaded}, '
            f'documents {run.documents_downloaded}, errors {run.errors}, media pending {run.media_pending}',
        )
        if run.error_summary:
            self.stdout.write(run.error_summary)
