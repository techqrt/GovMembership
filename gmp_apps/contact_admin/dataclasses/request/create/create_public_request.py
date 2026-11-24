import dataclasses


@dataclasses.dataclass
class CreatePublicRequestRequest:
    category_id: int
    full_name: str
    description: str
    email: str | None = None
    mobile_number: str | None = None
    subject: str = ''
    website: str = ''   # honeypot: real visitors never see or fill it
