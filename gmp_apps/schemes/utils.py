from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from django.db.models import QuerySet

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.common.utils import Utils
from gmp_apps.schemes.classification import canonical_state
from gmp_apps.schemes.models import Scheme
from gmp_apps.schemes.models.scheme import SchemeLevel

SUMMARY_CHARS = 220


def tag_filter(group: str) -> Callable[[QuerySet, str], QuerySet]:
    """Filter by a tag of one group. Both conditions sit in one filter() so they match the same tag row."""
    return lambda queryset, value: queryset.filter(tags__group=group, tags__name=value)


def level_filter(queryset: QuerySet, value: str) -> QuerySet:
    if value not in SchemeLevel.values:
        raise ValueError(Constants.bad_filter_value)
    return queryset.filter(level=value)


def state_filter(queryset: QuerySet, value: str) -> QuerySet:
    """Matches a state's schemes whatever spelling the app sends (the member's profile state is free text)."""
    wanted = canonical_state(value)
    if wanted is None:
        raise ValueError(Constants.bad_filter_value)
    return queryset.filter(state=wanted)


class SchemeUtils:
    filter_columns: dict[str, Any] = {
        'department': 'department',
        'level': level_filter,
        'state': state_filter,
        'schemeType': tag_filter('scheme_type'),
        'personType': tag_filter('person_type'),
        'caste': tag_filter('caste'),
    }
    sort_columns: dict[str, str] = {
        'schemeId': 'scheme_id', 'title': 'title', 'department': 'department',
        'updatedDateTime': 'updated_date_time', 'createdDateTime': 'created_date_time',
    }
    search_columns: list[str] = ['title', 'department', 'description', 'eligibility', 'benefits', 'highlights']

    @staticmethod
    def base_url(request_url: str) -> str:
        return Utils.public_base_url(request_url)

    @staticmethod
    def image_urls(scheme: Scheme, base: str) -> list[str]:
        """Pictures as URLs on OUR server. (The scheme's `images` are prefetched by the views.)"""
        urls = [image.file.url for image in scheme.images.all()]
        return [url if url.startswith(('http://', 'https://')) else f'{base}{url}' for url in urls]

    @staticmethod
    def documents(scheme: Scheme, base: str) -> list[dict[str, Any]]:
        """PDFs stored on OUR server (brochure, guidelines). The source's own file URLs never leave."""
        rows: list[dict[str, Any]] = []
        for document in scheme.documents.all():
            url = document.file.url
            rows.append({
                'kind': document.kind,
                'label': document.label or 'Document',
                'url': url if url.startswith(('http://', 'https://')) else f'{base}{url}',
                'sizeBytes': document.size_bytes,
            })
        return rows

    @staticmethod
    def public_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
        """Links members may see: nothing that points back at the source site."""
        return [link for link in links if urlsplit(link.get('url', '')).netloc.lower() != Configurations.scheme_source_host]

    @staticmethod
    def summary(text: str) -> str:
        flat = ' '.join(line.lstrip('- ').strip() for line in text.splitlines() if line.strip())
        return flat if len(flat) <= SUMMARY_CHARS else flat[:SUMMARY_CHARS].rsplit(' ', 1)[0] + '…'

    @staticmethod
    def list_row(scheme: Scheme, base: str) -> dict[str, Any]:
        images = SchemeUtils.image_urls(scheme, base)
        return {
            'schemeId': scheme.scheme_id,
            'title': scheme.title,
            'department': scheme.department,
            'summary': SchemeUtils.summary(scheme.description or scheme.benefits),
            'imageUrl': images[0] if images else None,
            'tags': SchemeUtils.tags(scheme),
            'isActive': scheme.is_accepting_applications,
            'level': scheme.level or None,
            'state': scheme.state or None,
            'updatedDateTime': scheme.updated_date_time,
        }

    @staticmethod
    def tags(scheme: Scheme) -> list[dict[str, str]]:
        return [{'group': tag.group, 'name': tag.name} for tag in scheme.tags.all()]  # prefetched by the views

    @staticmethod
    def detail_row(scheme: Scheme, base: str) -> dict[str, Any]:
        """Member-facing detail. Review state, sync internals, admin identity and the source URL are never included."""
        return {
            'schemeId': scheme.scheme_id,
            'title': scheme.title,
            'department': scheme.department,
            'description': scheme.description,
            'eligibility': scheme.eligibility,
            'benefits': scheme.benefits,
            'applicationProcedure': scheme.application_procedure,
            'requiredDocuments': scheme.required_documents,
            'highlights': scheme.highlights,
            'contactDetails': scheme.contact_details,
            'overview': scheme.overview,
            'links': SchemeUtils.public_links(scheme.links),
            'documents': SchemeUtils.documents(scheme, base),
            'additionalSections': scheme.additional_sections,
            'tags': SchemeUtils.tags(scheme),
            'images': SchemeUtils.image_urls(scheme, base),
            'isActive': scheme.is_accepting_applications,
            'level': scheme.level or None,
            'state': scheme.state or None,
            'publishedDateTime': scheme.published_date_time,
            'updatedDateTime': scheme.updated_date_time,
        }
