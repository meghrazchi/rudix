"""Plain snapshots of the configuration rows a chat run reads (R05-02).

The read session is committed and released after stage 4, so later stages must not touch
ORM objects loaded there. ``resolve_config`` copies the values it needs into these frozen
dataclasses; they keep the attribute names of the ORM models the helpers read.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.models.prompt_template import PromptTemplateVersion
from app.models.rag_profile import RagProfile


@dataclass(frozen=True)
class RagProfileSnapshot:
    id: UUID
    name: str
    version: int
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, profile: RagProfile) -> "RagProfileSnapshot":
        return cls(
            id=profile.id,
            name=profile.name,
            version=profile.version,
            config=dict(profile.config or {}),
        )


@dataclass(frozen=True)
class PromptVersionSnapshot:
    id: UUID
    version_number: int
    content: str

    @classmethod
    def from_model(cls, version: PromptTemplateVersion) -> "PromptVersionSnapshot":
        return cls(id=version.id, version_number=version.version_number, content=version.content)
