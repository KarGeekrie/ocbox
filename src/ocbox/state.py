"""Persisted per-project state: what package set was last baked into which image tag."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ProjectState:
    packages_fingerprint: str | None = None
    image_tag: str | None = None

    @classmethod
    def load(cls, state_dir: Path) -> ProjectState:
        path = state_dir / "state.json"
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return cls()
        return cls(
            packages_fingerprint=data.get("packages_fingerprint"),
            image_tag=data.get("image_tag"),
        )

    def save(self, state_dir: Path) -> None:
        path = state_dir / "state.json"
        path.write_text(json.dumps(asdict(self), indent=2))
