import dataclasses


@dataclasses.dataclass
class ChangePasswordRequest:
    old_password: str
    new_password: str
