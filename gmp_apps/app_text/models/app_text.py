from django.core.validators import RegexValidator
from django.db import models

SUPPORTED_LANGUAGES = ('en', 'hi')
FALLBACK_LANGUAGE = 'en'

key_validator = RegexValidator(r'^[a-z][a-z0-9_.]{1,99}$', 'Use lower-case letters, digits, "_" and "." only, starting with a letter (for example home.title)')


class AppText(models.Model):
    """One piece of app text in English and Hindi, edited by an admin. The app asks for the strings of one language;
    a missing Hindi text falls back to the English one. Nothing is hard-coded in the backend."""

    text_id = models.BigAutoField(primary_key=True)
    key = models.CharField(max_length=100, unique=True, validators=[key_validator], help_text='The name the app uses, for example home.title')
    text_en = models.CharField('English text', max_length=1000)
    text_hi = models.CharField('Hindi text', max_length=1000, blank=True, default='', help_text='Leave empty to show the English text')
    is_active = models.BooleanField(default=True)
    created_date_time = models.DateTimeField(auto_now_add=True)
    updated_date_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_text'
        ordering = ['key']

    def __str__(self) -> str:
        return self.key

    def text_for(self, language: str) -> str:
        return (self.text_hi or self.text_en) if language == 'hi' else self.text_en
