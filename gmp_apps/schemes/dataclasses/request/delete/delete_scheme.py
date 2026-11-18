import dataclasses


@dataclasses.dataclass
class DeleteSchemeRequest:
    scheme_id: int
