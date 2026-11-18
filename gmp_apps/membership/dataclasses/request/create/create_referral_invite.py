import dataclasses


@dataclasses.dataclass
class CreateReferralInviteRequest:
    full_name: str
    email: str | None = None
    mobile_number: str | None = None
