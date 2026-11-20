from django.core.management.base import BaseCommand

from gmp_apps.authentication.identity import KINDS
from gmp_apps.authentication.models import User
from gmp_apps.common import field_encryption


class Command(BaseCommand):
    help = (
        'Re-encrypt every stored Aadhaar/PAN with the FIRST key in FIELD_ENCRYPTION_KEYS and rebuild its lookup hash. '
        'Run after adding a new first key (key rotation). Keep the old keys in the list until this finishes. '
        'Prints counts and membership IDs only, never numbers.'
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('--dry-run', action='store_true', help='Check that every value can be decrypted; change nothing')

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options['dry_run'])
        done, failed = 0, []
        for user in User.objects.exclude(aadhaar_encrypted='', pan_encrypted='').iterator():
            columns: list[str] = []
            try:
                for kind in KINDS:
                    value = user.reveal_government_id(kind)
                    if value:
                        columns += user.set_government_id(kind, value)
            except field_encryption.DecryptionError:
                failed.append(user.membership_id)
                continue
            if columns and not dry_run:
                user.save(update_fields=columns)
            done += 1
        verb = 'Checked' if dry_run else 'Re-encrypted'
        self.stdout.write(f'{verb} {done} member(s); {len(failed)} could not be decrypted.')
        if failed:
            self.stdout.write('Cannot decrypt (key missing?): ' + ', '.join(failed[:50]))
            raise SystemExit(1)
