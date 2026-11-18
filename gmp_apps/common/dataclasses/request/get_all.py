import dataclasses
from datetime import date


@dataclasses.dataclass
class GetAll:
    page_num: int = 1
    limit: int = 10
    sort_by: str = ''
    sort_order: str = 'asc'
    filter_key: str = ''
    filter_value: str = ''
    search_key: str = ''
    from_date: date | None = None
    to_date: date | None = None
    values: str = ''

    @property
    def values_list(self) -> list[str]:
        return [value.strip() for value in self.values.split(',') if value.strip()]
