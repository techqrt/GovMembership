from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.media import sha256_of
from gmp_apps.common.private_storage import private_storage
from gmp_apps.member_documents.files import display_name, has_dangerous_content, has_denied_extension, is_image, sniff_type


class DocumentType(models.TextChoices):
    AADHAAR = 'aadhaar', 'Aadhaar'
    PAN = 'pan', 'PAN'
    ADDRESS_PROOF = 'address_proof', 'Address proof'
    PROFILE_PHOTO = 'profile_photo', 'Profile photo'
    POLICE_VERIFICATION = 'police_verification', 'Police verification'
    CHARACTER_CERTIFICATE = 'character_certificate', 'Character certificate'
    FATHER_VERIFICATION = 'father_verification', 'Father verification letter'
    OTHER = 'other', 'Other'
    CONTACT_ATTACHMENT = 'contact_attachment', 'Contact Admin attachment'


# The documents a member may attach to a Permanent application as verification.
VERIFICATION_TYPES = (DocumentType.POLICE_VERIFICATION, DocumentType.CHARACTER_CERTIFICATE, DocumentType.FATHER_VERIFICATION)

def type_limit(document_type: str) -> int:
    """Files a member may hold of one type: a profile photo is one; contact attachments pile up across requests."""
    if document_type == DocumentType.PROFILE_PHOTO:
        return 1
    if document_type == DocumentType.CONTACT_ATTACHMENT:
        return Configurations.member_document_max_contact_attachments
    return Configurations.member_document_max_per_type


def document_upload_path(instance: 'MemberDocument', filename: str) -> str:
    return f'{instance.user_id}/{filename}'


class MemberDocument(models.Model):
    """A file a member uploaded about themselves. Private: only the owner and authorised admins can
    read it, through an authenticated download, never through a public URL.

    The stored name is the content hash; the uploader's file name is kept only as a sanitised label
    for the download name.
    """

    document_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=24, choices=DocumentType.choices)
    label = models.CharField(max_length=100, blank=True, default='')
    file = models.FileField(upload_to=document_upload_path, storage=private_storage, max_length=255)
    download_name = models.CharField(max_length=130, editable=False)
    content_type = models.CharField(max_length=40, editable=False)
    sha256 = models.CharField(max_length=64, editable=False)
    size_bytes = models.PositiveIntegerField(default=0, editable=False)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'member_document'
        ordering = ['-created_date_time', '-document_id']
        constraints = [models.UniqueConstraint(fields=['user', 'sha256'], name='unique_member_document_content')]
        permissions = [('download_memberdocument', 'Can download members\' documents')]

    def __str__(self) -> str:
        return f'{self.document_type} #{self.document_id}'

    @staticmethod
    def check_upload(user: User, document_type: str, original_name: str, data: bytes) -> tuple[str, str]:
        """Every rule for an upload, before anything is written. Returns (extension, content type)."""
        if not data:
            raise ValueError(Constants.document_empty)
        if len(data) > Configurations.member_document_max_bytes:
            raise ValueError(f'The file is too large (limit {Configurations.member_document_max_bytes // 1_000_000} MB)')
        if has_denied_extension(original_name) or has_dangerous_content(data):
            raise ValueError(Constants.document_refused_type)
        extension, content_type = sniff_type(data)
        if document_type == DocumentType.PROFILE_PHOTO and not is_image(content_type):
            raise ValueError(Constants.document_photo_image_only)
        owned = MemberDocument.objects.filter(user=user)
        if owned.filter(sha256=sha256_of(data)).exists():
            raise ValueError(Constants.document_duplicate)
        if owned.count() >= Configurations.member_document_max_per_member:
            raise ValueError(Constants.document_limit_total)
        if owned.filter(document_type=document_type).count() >= type_limit(document_type):
            raise ValueError(Constants.document_limit_type)
        return extension, content_type

    @staticmethod
    def resolve_own(user_id: int, document_ids: list[int], types: tuple[str, ...], message: str) -> list['MemberDocument']:
        """The caller's own documents of the allowed types. A foreign, a missing and a wrong-type id all give the
        one same refusal, so the answer reveals nothing about other members' files."""
        wanted = set(document_ids)
        found = list(MemberDocument.objects.filter(document_id__in=wanted, user_id=user_id, document_type__in=types))
        if len(found) != len(wanted):
            raise ValueError(message)
        return found

    @staticmethod
    def add(user: User, document_type: str, upload: Any, label: str = '') -> 'MemberDocument':
        """Validate, then store under the content hash. The member row is locked so two parallel
        uploads cannot both slip under the limits."""
        data = upload.read()
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            extension, content_type = MemberDocument.check_upload(user, document_type, upload.name or '', data)
            digest = sha256_of(data)
            document = MemberDocument(
                user=user, document_type=document_type, label=label.strip(), content_type=content_type, sha256=digest,
                size_bytes=len(data), download_name=display_name(upload.name or '', extension),
            )
            document.file.save(f'{digest[:32]}.{extension}', _Bytes(data), save=False)
            try:
                document.save()
            except Exception:
                document.file.delete(save=False)  # never leave an orphan file behind a failed insert
                raise
        return document


class _Bytes:
    """Minimal file object for FieldFile.save(): the bytes we already read and checked."""

    def __init__(self, data: bytes) -> None:
        self._data, self.size = data, len(data)

    def chunks(self, chunk_size: int = 65536):  # noqa: ANN201
        for start in range(0, len(self._data), chunk_size):
            yield self._data[start:start + chunk_size]

    def read(self, *args: Any) -> bytes:
        return self._data

    def seek(self, *args: Any) -> None:
        return None


@receiver(post_delete, sender=MemberDocument)
def remove_member_document_file(sender: type, instance: MemberDocument, **kwargs: Any) -> None:
    """Deleting the row (or the member) also removes the stored file."""
    if instance.file:
        instance.file.delete(save=False)
