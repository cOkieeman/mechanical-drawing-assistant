from __future__ import annotations

import sys
from pathlib import Path

from mechanical_drawing_assistant.models import JsonObject


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path | None:
    root = getattr(sys, "_MEIPASS", None)
    if isinstance(root, str) and root:
        return Path(root)
    return None


def application_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative

    bundled = bundle_root()
    if bundled is not None:
        bundled_path = bundled / relative
        if bundled_path.exists():
            return bundled_path

    app_path = application_root() / relative
    if app_path.exists() or is_frozen():
        return app_path
    return project_root() / relative


def default_knowledge_path() -> Path:
    return resource_path("knowledge")


def default_samples_path() -> Path:
    return resource_path("samples")


def runtime_info() -> JsonObject:
    bundled = bundle_root()
    return {
        "frozen": is_frozen(),
        "executable": str(Path(sys.executable).resolve()),
        "application_root": str(application_root()),
        "bundle_root": str(bundled) if bundled else None,
        "default_knowledge_path": str(default_knowledge_path()),
        "default_samples_path": str(default_samples_path()),
    }
