import dataclasses
from datetime import date


@dataclasses.dataclass
class UpdateProfileRequest:
    full_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    state: str | None = None
    city: str | None = None

    def changed_fields(self) -> dict[str, object]:
        return {
            name: value
            for name, value in dataclasses.asdict(self).items()
            if value is not None
        }
