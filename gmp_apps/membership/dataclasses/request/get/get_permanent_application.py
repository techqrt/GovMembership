import dataclasses


@dataclasses.dataclass
class GetPermanentApplicationRequest:
    application_id: int
