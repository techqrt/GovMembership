import dataclasses


@dataclasses.dataclass
class RefreshTokenRequest:
    refresh: str
