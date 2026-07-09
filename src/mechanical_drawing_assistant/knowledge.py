from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mechanical_drawing_assistant.models import DimensionIntent, JsonObject


class KnowledgeBase:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load_standard_index(self) -> list[JsonObject]:
        data = self._read_json(self.root / "standards" / "gb_index.json")
        standards = data.get("standards", [])
        if not isinstance(standards, list):
            raise ValueError("knowledge/standards/gb_index.json: `standards` must be a list.")
        return [standard for standard in standards if isinstance(standard, dict)]

    def load_standard_profile(self, drawing_standard: str) -> JsonObject | None:
        profile_name = self._standard_profile_name(drawing_standard)
        if not profile_name:
            return None
        return self._read_json(self.root / "standards" / "profiles" / f"{profile_name}.json")

    def load_dimension_intents(self, template_names: list[str]) -> list[DimensionIntent]:
        intents: list[DimensionIntent] = []
        for template_name in template_names:
            template = self._read_json(self.root / "features" / f"{template_name}.json")
            raw_intents = template.get("dimension_intents", [])
            if not isinstance(raw_intents, list):
                raise ValueError(f"{template_name}.json: `dimension_intents` must be a list.")
            for raw_intent in raw_intents:
                if not isinstance(raw_intent, dict):
                    raise ValueError(
                        f"{template_name}.json contains a non-object dimension intent."
                    )
                intents.append(DimensionIntent.from_mapping(raw_intent, template_name))
        return intents

    def _read_json(self, path: Path) -> JsonObject:
        if not path.exists():
            raise FileNotFoundError(f"Knowledge file not found: {path}")
        with path.open("r", encoding="utf-8") as file:
            data: Any = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"Knowledge file must contain a JSON object: {path}")
        return data

    def _standard_profile_name(self, drawing_standard: str) -> str | None:
        normalized = drawing_standard.strip().upper()
        if normalized in {"GB", "GB_MECHANICAL_DRAWING"}:
            return "gb_mechanical_drawing"
        return None
