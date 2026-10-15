from dataclasses import dataclass, field


@dataclass
class Reply:
    text: str
    photos: list[tuple[str, str]] = field(default_factory=list)  # (image_url, caption)
