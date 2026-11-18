import dataclasses


@dataclasses.dataclass
class CancelReferralInviteRequest:
    invite_id: int
