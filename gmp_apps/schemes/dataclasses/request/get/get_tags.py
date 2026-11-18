import dataclasses


@dataclasses.dataclass
class GetTagsRequest:
    group: str = ''
