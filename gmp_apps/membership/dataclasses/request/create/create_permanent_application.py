import dataclasses


@dataclasses.dataclass
class CreatePermanentApplicationRequest:
    reason: str
