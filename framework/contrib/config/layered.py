from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def load_layered_config(base_path: str | Path, overrides_path: str | Path | None = None) -> dict[str, Any]:
    base_file = Path(base_path)
    if not base_file.exists():
        raise FileNotFoundError(f"Base config file not found: {base_file}")

    base_data = _load_yaml_mapping(base_file)
    if overrides_path is None:
        return base_data

    override_file = Path(overrides_path)
    if not override_file.exists():
        return base_data

    override_data = _load_yaml_mapping(override_file)
    merged = _deep_merge(base_data, override_data)
    if not isinstance(merged, dict):
        raise ValueError("Merged config root must be a mapping")
    return merged


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load YAML config files") from exc

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config root must be a mapping in {path}")
    return deepcopy(loaded)


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged: dict[Any, Any] = deepcopy(base)
        for key, override_value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], override_value)
            else:
                merged[key] = deepcopy(override_value)
        return merged

    return deepcopy(override)