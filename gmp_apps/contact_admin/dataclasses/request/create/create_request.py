import dataclasses


@dataclasses.dataclass
class CreateRequestRequest:
    category_id: int
    subject: str
    description: str
