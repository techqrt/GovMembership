import dataclasses


@dataclasses.dataclass
class MarkReadRequest:
    notification_id: int | None = None
    mark_all: bool = False
