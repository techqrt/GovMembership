import dataclasses


@dataclasses.dataclass
class ResendOtpRequest:
    identifier: str
