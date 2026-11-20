import dataclasses
from typing import Any


@dataclasses.dataclass
class CreateDocumentRequest:
    document_type: str
    file: Any
    label: str = ''
