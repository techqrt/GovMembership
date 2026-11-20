import dataclasses


@dataclasses.dataclass
class GetDocumentRequest:
    document_id: int
