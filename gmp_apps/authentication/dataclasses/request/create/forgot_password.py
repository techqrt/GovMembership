import dataclasses


@dataclasses.dataclass
class ForgotPasswordRequest:
    identifier: str
