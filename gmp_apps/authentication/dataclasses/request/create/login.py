import dataclasses


@dataclasses.dataclass
class LoginRequest:
    identifier: str
    password: str
