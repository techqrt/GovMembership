from django.db import models


class TagGroup(models.TextChoices):
    SCHEME_TYPE = 'scheme_type', 'Scheme type'
    PERSON_TYPE = 'person_type', 'Person type'
    CASTE = 'caste', 'Caste'


class SchemeTag(models.Model):
    """A classification of a scheme (e.g. scheme type 'Pension', person type 'Labour'). A real table
    rather than JSON so members can filter by it on any database."""

    tag_id = models.BigAutoField(primary_key=True)
    scheme = models.ForeignKey('schemes.Scheme', on_delete=models.CASCADE, related_name='tags')
    group = models.CharField(max_length=16, choices=TagGroup.choices)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'scheme_tag'
        constraints = [models.UniqueConstraint(fields=['scheme', 'group', 'name'], name='unique_scheme_tag')]
        indexes = [models.Index(fields=['group', 'name'])]
        ordering = ['group', 'name']

    def __str__(self) -> str:
        return f'{self.group}: {self.name}'
