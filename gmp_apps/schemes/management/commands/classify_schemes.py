from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gmp_apps.schemes.classification import classify
from gmp_apps.schemes.models import Scheme

FROZEN = ('status', 'content_hash', 'updated_date_time', 'locally_edited', 'published_date_time', 'department', 'title')


def snapshot() -> dict[int, tuple]:
    """Everything the fill must leave alone, for every scheme."""
    return {row[0]: row[1:] for row in Scheme.objects.values_list('pk', *FROZEN)}


class Command(BaseCommand):
    help = (
        'Fill the national/state level of schemes that have none, from their department, title and page address. '
        'By default only PREVIEWS (writes nothing). --apply writes the two level columns and nothing else, in one '
        'transaction, and rolls everything back if any scheme changed in any other way. Schemes that already have a '
        'level are never touched, so it is safe to run again.'
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('--apply', action='store_true', help='Write the proposed levels (default: preview only)')
        parser.add_argument('--show', type=int, default=200, help='How many rows of the preview to print')

    def handle(self, *args: object, **options: object) -> None:
        todo = list(Scheme.objects.filter(level='').order_by('scheme_id').values('scheme_id', 'status', 'title', 'department', 'source_url'))
        proposals = [(row, classify(row['department'], row['title'], row['source_url'])) for row in todo]
        for row, guess in proposals[: int(options['show'])]:
            label = f'{guess.level}/{guess.state}' if guess.state else (guess.level or 'NOT SET')
            self.stdout.write(f"#{row['scheme_id']} [{row['status']}] {row['title'][:50]!r} -> {label} ({guess.reason})")
        national = sum(1 for _, g in proposals if g.level == 'national')
        state = sum(1 for _, g in proposals if g.level == 'state')
        unclear = len(proposals) - national - state
        self.stdout.write(f'\nWithout a level: {len(proposals)}. Would set: {national} national, {state} state. Left unset: {unclear}.')
        if not options['apply']:
            self.stdout.write('Preview only, nothing was written. Run again with --apply to write.')
            return
        before = snapshot()
        with transaction.atomic():  # raising inside rolls every write back
            for row, guess in proposals:
                if guess.level:
                    Scheme.objects.filter(pk=row['scheme_id'], level='').update(level=guess.level, state=guess.state)
            if snapshot() != before:
                raise CommandError('Some scheme changed in a way other than its level: nothing was written.')
        self.stdout.write(self.style.SUCCESS(
            f'Done: {national + state} scheme(s) classified. Status, content, edit flags and update times are unchanged.'
        ))
