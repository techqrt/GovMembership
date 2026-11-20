import dataclasses


@dataclasses.dataclass
class CreatePermanentApplicationRequest:
    reason: str
    document_ids: list[int] | None = None
    declaration_accepted: bool = False
