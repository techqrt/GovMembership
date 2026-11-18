from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from gmp_apps.schemes.images import ALLOWED_TYPES_TEXT, sha256_of, sniff_image_extension, validate_image_upload


def image_upload_path(instance: 'SchemeImage', filename: str) -> str:
    return f'schemes/{instance.scheme_id}/{filename}'


class SchemeImage(models.Model):
    """A scheme picture stored in OUR media storage and served from our own URL.

    Imported images are downloaded once during the sync (`source_url` is kept for our logs only and
    is never returned to clients); admins can also upload their own.
    """

    image_id = models.BigAutoField(primary_key=True)
    scheme = models.ForeignKey('schemes.Scheme', on_delete=models.CASCADE, related_name='images')
    file = models.FileField(upload_to=image_upload_path, validators=[validate_image_upload], max_length=255)
    sha256 = models.CharField(max_length=64, editable=False)
    position = models.PositiveSmallIntegerField(default=0)
    source_url = models.URLField(max_length=500, null=True, blank=True, editable=False)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scheme_image'
        ordering = ['position', 'image_id']
        constraints = [models.UniqueConstraint(fields=['scheme', 'sha256'], name='unique_scheme_image_content')]

    def __str__(self) -> str:
        return f'Image {self.image_id} of scheme {self.scheme_id}'

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
            if sniff_image_extension(data[:16]) is None:
                raise ValidationError(f'Upload a {ALLOWED_TYPES_TEXT} image')
            if self.scheme_id and SchemeImage.objects.filter(scheme_id=self.scheme_id, sha256=sha256_of(data)).exclude(pk=self.pk).exists():
                raise ValidationError('This image is already attached to the scheme')

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Name the file after its content and type (never after what the uploader called it)."""
        if self._new_upload():
            data = self._read_upload()
            extension = sniff_image_extension(data[:16])
            if extension is None:
                raise ValidationError(f'Upload a {ALLOWED_TYPES_TEXT} image')
            self.sha256 = sha256_of(data)
            if SchemeImage.objects.filter(scheme_id=self.scheme_id, sha256=self.sha256).exclude(pk=self.pk).exists():
                return  # same picture already attached: nothing to add
            self.file.name = f'{self.sha256[:24]}.{extension}'
        super().save(*args, **kwargs)


@receiver(post_delete, sender=SchemeImage)
def remove_image_file(sender, instance: SchemeImage, **kwargs) -> None:  # noqa: ANN003
    """Deleting the row (or its scheme) also removes the stored file."""
    if instance.file:
        instance.file.delete(save=False)
