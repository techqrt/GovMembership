import dataclasses


@dataclasses.dataclass
class AskRequest:
    question: str
