import dataclasses


@dataclasses.dataclass
class VerifyOtpRequest:
    identifier: str
    otp: str
