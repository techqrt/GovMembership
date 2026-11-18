import dataclasses


@dataclasses.dataclass
class RegisterUserRequest:
    full_name: str
    password: str
    email: str | None = None
    mobile_number: str | None = None
    referral_code: str | None = None
