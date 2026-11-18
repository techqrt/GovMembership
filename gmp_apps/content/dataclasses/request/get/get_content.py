import dataclasses


@dataclasses.dataclass
class GetContentRequest:
    content_id: int
