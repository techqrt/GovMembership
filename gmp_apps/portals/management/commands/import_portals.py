import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gmp_apps.portals.models import ComplaintPortal, PortalCategory
from gmp_apps.portals.validators import url_key

DEFAULT_FILE = Path(__file__).resolve().parents[2] / 'data' / 'uttar_pradesh_portals.csv'
CATEGORY_BY_JURISDICTION = {'India': 'India (National)', 'Uttar Pradesh': 'Uttar Pradesh'}
NO_VALUE = {'', '-', '—', '–'}


def _clean(value: str) -> str:
    value = (value or '').strip()
    return '' if value in NO_VALUE else value


def _description(row: dict[str, str], also: list[str]) -> str:
    parts = [_clean(row['Complaint Type / Scope'])]
    if _clean(row['Phone Number / Helpline']):
        parts.append(f"Helpline: {_clean(row['Phone Number / Helpline'])}")
    if _clean(row['Usage Notes']):
        parts.append(_clean(row['Usage Notes']))
    if also:
        parts.append('Other channels on this site: ' + '; '.join(also) + '.')
    return ' '.join(p if p.endswith(('.', ')')) else p + '.' for p in parts if p)[:2000]


class Command(BaseCommand):
    help = 'Load complaint portals from a CSV (default: the bundled India + Uttar Pradesh list). Safe to re-run: portals are matched by official URL.'

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('--file', default=str(DEFAULT_FILE))

    @transaction.atomic
    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        path = Path(options['file'])
        if not path.exists():
            raise CommandError(f'File not found: {path}')
        with path.open(newline='', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(url_key(row['Official Website URL'].strip()), []).append(row)
        categories = {}
        for order, (jurisdiction, name) in enumerate(CATEGORY_BY_JURISDICTION.items()):
            categories[jurisdiction], _ = PortalCategory.objects.get_or_create(name=name, defaults={'sort_order': order})
        created = updated = 0
        for order, group in enumerate(groups.values()):
            first = group[0]
            category = categories.get(first['Jurisdiction'].strip())
            if category is None:
                raise CommandError(f"Unknown jurisdiction: {first['Jurisdiction']}")
            values = {
                'name': first['Portal / Complaint Channel'].strip()[:200],
                'department': first['Department / Authority'].strip()[:200],
                'description': _description(first, [r['Portal / Complaint Channel'].strip() for r in group[1:]]),
                'category': category,
                'sort_order': min(order, 65535),
            }
            portal = ComplaintPortal.objects.filter(url_key=url_key(first['Official Website URL'].strip())).first()
            if portal is None:
                ComplaintPortal(official_url=first['Official Website URL'].strip(), **values).save()
                created += 1
            else:
                for field, value in values.items():
                    setattr(portal, field, value)
                portal.save()
                updated += 1
        self.stdout.write(self.style.SUCCESS(f'{len(rows)} rows -> {len(groups)} portals: {created} created, {updated} updated'))
