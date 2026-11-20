import dataclasses


@dataclasses.dataclass
class CreateRequestRequest:
    category_id: int
    subject: str
    description: str
    priority: str = 'normal'
    attachment_ids: list[int] | None = None
