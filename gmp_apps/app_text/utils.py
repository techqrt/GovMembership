from typing import Any

from gmp_apps.app_text.models import AppText


class AppTextUtils:
    @staticmethod
    def strings(language: str) -> dict[str, Any]:
        """Active strings in one language (Hindi falls back to English per string) and when any of them last changed."""
        rows = list(AppText.objects.filter(is_active=True).values_list('key', 'text_en', 'text_hi', 'updated_date_time'))
        use_hindi = language == 'hi'
        return {
            'language': language,
            'lastUpdated': max((row[3] for row in rows), default=None),
            'strings': {key: (hindi or english) if use_hindi else english for key, english, hindi, _ in rows},
        }
