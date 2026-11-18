from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from gmp_apps.schemes.documents import looks_like_pdf, validate_pdf_upload
from gmp_apps.schemes.images import sha256_of


def document_upload_path(instance: 'SchemeDocument', filename: str) -> str:
    return f'schemes/{instance.scheme_id}/docs/{filename}'


class DocumentKind(models.TextChoices):
    BROCHURE = 'brochure', 'Brochure'
    DOCUMENT = 'document', 'Document'


class SchemeDocument(models.Model):
    """A PDF (brochure, guidelines) stored in OUR media storage and served from our own URL.

    Imported documents are downloaded once during the sync (`source_url` is kept for our logs only
    and is never returned to clients); admins can also upload their own.
    """

    document_id = models.BigAutoField(primary_key=True)
    scheme = models.ForeignKey('schemes.Scheme', on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to=document_upload_path, validators=[validate_pdf_upload], max_length=255)
    label = models.CharField(max_length=200, blank=True, default='')
    kind = models.CharField(max_length=16, choices=DocumentKind.choices, default=DocumentKind.DOCUMENT)
    sha256 = models.CharField(max_length=64, editable=False)
    size_bytes = models.PositiveIntegerField(default=0, editable=False)
    position = models.PositiveSmallIntegerField(default=0)
    source_url = models.URLField(max_length=500, null=True, blank=True, editable=False)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scheme_document'
        ordering = ['position', 'document_id']
        constraints = [models.UniqueConstraint(fields=['scheme', 'sha256'], name='unique_scheme_document_content')]

    def __str__(self) -> str:
        return self.label or f'Document {self.document_id}'

    def _new_upload(self) -> bool:
        return bool(self.file) and not self.file._committed

    def _read_upload(self) -> bytes:
        self.file.seek(0)
        data = self.file.read()
        self.file.seek(0)
        return data

    def clean(self) -> None:
        if self._new_upload():
            data = self._read_upload()
            if not looks_like_pdf(data[:8]):
                raise ValidationError('Upload a PDF document')
            if self.scheme_id and SchemeDocument.objects.filter(scheme_id=self.scheme_id, sha256=sha256_of(data)).exclude(pk=self.pk).exists():
                raise ValidationError('This document is already attached to the scheme')

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Name the file after its content (never after what the uploader called it)."""
        if self._new_upload():
            data = self._read_upload()
            if not looks_like_pdf(data[:8]):
                raise ValidationError('Upload a PDF document')
            self.sha256 = sha256_of(data)
            self.size_bytes = len(data)
            if SchemeDocument.objects.filter(scheme_id=self.scheme_id, sha256=self.sha256).exclude(pk=self.pk).exists():
                return  # same document already attached: nothing to add
            self.file.name = f'{self.sha256[:24]}.pdf'
        super().save(*args, **kwargs)


@receiver(post_delete, sender=SchemeDocument)
def remove_document_file(sender, instance: SchemeDocument, **kwargs) -> None:  # noqa: ANN003
    """Deleting the row (or its scheme) also removes the stored file."""
    if instance.file:
        instance.file.delete(save=False)
