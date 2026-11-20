import dataclasses


@dataclasses.dataclass
class RegisterUserRequest:
    full_name: str
    password: str
    email: str | None = None
    mobile_number: str | None = None
    referral_code: str | None = None
    father_name: str | None = None
    profession: str | None = None
    area_type: str | None = None
    mandal: str | None = None
    ward_village: str | None = None
    house_street: str | None = None
    pin_code: str | None = None
    aadhaar_number: str | None = None
    pan_number: str | None = None
    app_language: str | None = None
    declaration_accepted: bool = False
