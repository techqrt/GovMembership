import dataclasses
from datetime import date


@dataclasses.dataclass
class UpdateProfileRequest:
    full_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    state: str | None = None
    city: str | None = None
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

    def changed_fields(self) -> dict[str, object]:
        return {
            name: value
            for name, value in dataclasses.asdict(self).items()
            if value is not None
        }
