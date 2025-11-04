import dataclasses

@dataclasses.dataclass
class Command:
    type: str
    value: str | None = None
    extra: str | None = None
