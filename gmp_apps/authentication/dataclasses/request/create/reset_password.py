import dataclasses


@dataclasses.dataclass
class ResetPasswordRequest:
    identifier: str
    otp: str
    new_password: str
