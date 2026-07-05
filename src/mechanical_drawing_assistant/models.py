from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
DEFAULT_GB_THREE_VIEWS = ["front", "top", "left"]


@dataclass(frozen=True)
class PartInput:
    name: str
    category: str
    source_model: str | None = None
    source_dwg: str | None = None
    material: str | None = None
    process: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> PartInput:
        return cls(
            name=required_text(data, "name"),
            category=required_text(data, "category"),
            source_model=optional_text(data, "source_model"),
            source_dwg=optional_text(data, "source_dwg"),
            material=optional_text(data, "material"),
            process=list_of_text(data.get("process", []), "part.process"),
            notes=list_of_text(data.get("notes", []), "part.notes"),
        )


@dataclass(frozen=True)
class OutputSpec:
    workdir: str
    drawing_basename: str
    export_formats: list[str] = field(default_factory=lambda: ["dwg", "pdf"])

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OutputSpec:
        return cls(
            workdir=required_text(data, "workdir"),
            drawing_basename=required_text(data, "drawing_basename"),
            export_formats=list_of_text(
                data.get("export_formats", ["dwg", "pdf"]),
                "output.export_formats",
            ),
        )


@dataclass(frozen=True)
class DrawingJob:
    job_name: str
    part: PartInput
    output: OutputSpec
    drawing_standard: str = "GB"
    feature_templates: list[str] = field(default_factory=list)
    views: list[str] = field(default_factory=lambda: DEFAULT_GB_THREE_VIEWS.copy())

    @classmethod
    def from_mapping(cls, data: JsonObject) -> DrawingJob:
        return cls(
            job_name=required_text(data, "job_name"),
            part=PartInput.from_mapping(required_object(data, "part")),
            output=OutputSpec.from_mapping(required_object(data, "output")),
            drawing_standard=optional_text(data, "drawing_standard") or "GB",
            feature_templates=list_of_text(data.get("feature_templates", []), "feature_templates"),
            views=list_of_text(data.get("views", DEFAULT_GB_THREE_VIEWS), "views"),
        )


@dataclass(frozen=True)
class DimensionIntent:
    intent_id: str
    label: str
    feature_type: str
    required: bool
    source: str
    standard_refs: list[str] = field(default_factory=list)
    placement_hint: str | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: JsonObject, source: str) -> DimensionIntent:
        return cls(
            intent_id=required_text(data, "id"),
            label=required_text(data, "label"),
            feature_type=required_text(data, "feature_type"),
            required=bool(data.get("required", True)),
            source=source,
            standard_refs=list_of_text(data.get("standard_refs", []), f"{source}.standard_refs"),
            placement_hint=optional_text(data, "placement_hint"),
            notes=list_of_text(data.get("notes", []), f"{source}.notes"),
        )

    def to_mapping(self) -> JsonObject:
        return {
            "id": self.intent_id,
            "label": self.label,
            "feature_type": self.feature_type,
            "required": self.required,
            "source": self.source,
            "standard_refs": self.standard_refs,
            "placement_hint": self.placement_hint,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class DrawingPlan:
    job_name: str
    part: PartInput
    views: list[str]
    standards: list[JsonObject]
    dimension_intents: list[DimensionIntent]
    planned_outputs: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_mapping(self) -> JsonObject:
        return {
            "job_name": self.job_name,
            "part": {
                "name": self.part.name,
                "category": self.part.category,
                "source_model": self.part.source_model,
                "source_dwg": self.part.source_dwg,
                "material": self.part.material,
                "process": self.part.process,
                "notes": self.part.notes,
            },
            "views": self.views,
            "standards": self.standards,
            "dimension_intents": [intent.to_mapping() for intent in self.dimension_intents],
            "planned_outputs": self.planned_outputs,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    code: str
    message: str
    recommendation: str

    def to_markdown(self) -> str:
        return f"- **{self.severity} / {self.code}**: {self.message}\n  建议：{self.recommendation}"


def path_exists(path_text: str | None) -> bool:
    if not path_text:
        return False
    return Path(path_text).exists()


def required_object(data: JsonObject, key: str) -> JsonObject:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"`{key}` must be an object.")
    return value


def required_text(data: JsonObject, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{key}` must be a non-empty string.")
    return value


def optional_text(data: JsonObject, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{key}` must be a string when provided.")
    value = value.strip()
    return value or None


def list_of_text(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"`{name}` must be a list.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"`{name}` must only contain non-empty strings.")
        result.append(item)
    return result
