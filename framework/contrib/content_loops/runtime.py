from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .processor import ContentLoopProcessor
from .registries import CommandRegistry, DetectorRegistry
from .schema import LoopDefinition
from .yaml_loader import load_loops_from_file


def build_processor_from_yaml(
    yaml_path: str | Path,
    *,
    loop_name: str,
    command_registry: CommandRegistry,
    detector_registry: DetectorRegistry,
) -> tuple[ContentLoopProcessor, Mapping[str, LoopDefinition]]:
    loop_definitions = load_loops_from_file(yaml_path)
    processor = ContentLoopProcessor(
        loop_definitions=loop_definitions,
        command_registry=command_registry,
        detector_registry=detector_registry,
        loop_name=loop_name,
    )
    return processor, loop_definitions