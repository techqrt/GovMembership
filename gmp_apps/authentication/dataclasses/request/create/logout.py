import dataclasses


@dataclasses.dataclass
class LogoutRequest:
    refresh: str
