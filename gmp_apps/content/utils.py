from typing import Any

from gmp_apps.content.models import ContentItem


class ContentUtils:
    filter_columns: dict[str, str] = {'type': 'content_type', 'categoryId': 'category_id'}
    sort_columns: dict[str, str] = {
        'contentId': 'content_id', 'title': 'title', 'type': 'content_type', 'publishedDateTime': 'publish_at',
        'createdDateTime': 'created_date_time',
    }
    search_columns: list[str] = ['title', 'summary', 'body', 'category__name']

    @staticmethod
    def row(item: ContentItem, base: str, with_body: bool = False) -> dict[str, Any]:
        """Member-facing shape. Status, minimum level, schedule end, author and internal ids are not included:
        a member only ever sees content they are allowed to read, and not how it was restricted."""
        cover = item.cover_image.url if item.cover_image else None
        row = {
            'contentId': item.content_id,
            'type': item.content_type,
            'title': item.title,
            'summary': item.summary,
            'categoryId': item.category_id,
            'categoryName': item.category.name,
            'coverImageUrl': (cover if cover.startswith(('http://', 'https://')) else f'{base}{cover}') if cover else None,
            'videoUrl': item.video_url,
            'durationSeconds': item.duration_seconds,
            'readMinutes': item.read_minutes,
            'isPinned': item.is_pinned,
            'publishedDateTime': item.publish_at,
        }
        if with_body:
            row['body'] = item.body
        return row
