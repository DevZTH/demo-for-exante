"""JSON dataset discovery and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from evals.models.schemas import EvalTestCase


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    name: str
    version: str
    cases: list[EvalTestCase]
    sources: tuple[Path, ...]


class DatasetError(ValueError):
    pass


def dataset_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise DatasetError(f"Dataset directory does not exist: {directory}")
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def list_datasets(directory: Path) -> list[tuple[str, int]]:
    listed: list[tuple[str, int]] = []
    for path in dataset_files(directory):
        bundle = _load_files([path], name=path.stem)
        listed.append((bundle.name, len(bundle.cases)))
    return listed


def load_dataset(
    name_or_path: str | Path,
    *,
    directory: Path,
    default_version: str = "1.0",
) -> DatasetBundle:
    value = Path(name_or_path)
    if str(name_or_path) == "all":
        paths = dataset_files(directory)
        if not paths:
            raise DatasetError(f"No JSON datasets found in {directory}")
        bundle = _load_files(paths, name="all")
    else:
        if value.suffix == ".json" or value.parent != Path("."):
            path = value.expanduser().resolve()
        else:
            path = directory / f"{value.name}.json"
        if not path.is_file():
            raise DatasetError(f"Dataset not found: {path}")
        bundle = _load_files([path], name=path.stem)

    if bundle.version == "unspecified":
        return DatasetBundle(
            name=bundle.name,
            version=default_version,
            cases=bundle.cases,
            sources=bundle.sources,
        )
    return bundle


def _load_files(paths: list[Path], *, name: str) -> DatasetBundle:
    cases: list[EvalTestCase] = []
    versions: set[str] = set()
    adapter = TypeAdapter(list[EvalTestCase])

    for path in paths:
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetError(f"Cannot read dataset {path}: {exc}") from exc

        if isinstance(payload, dict):
            raw_cases = payload.get("cases")
            version = payload.get("version", "unspecified")
            if not isinstance(version, str):
                raise DatasetError(f"Dataset version must be a string in {path}")
            versions.add(version)
        elif isinstance(payload, list):
            raw_cases = payload
            versions.add("unspecified")
        else:
            raise DatasetError(f"Dataset root must be an array or object in {path}")

        try:
            cases.extend(adapter.validate_python(raw_cases))
        except ValidationError as exc:
            raise DatasetError(f"Invalid test case in {path}: {exc}") from exc

    ids = [case.id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise DatasetError(f"Duplicate test case IDs: {', '.join(duplicates)}")

    versions.discard("unspecified")
    version = "+".join(sorted(versions)) if versions else "unspecified"
    return DatasetBundle(name=name, version=version, cases=cases, sources=tuple(paths))


__all__ = [
    "DatasetBundle",
    "DatasetError",
    "dataset_files",
    "list_datasets",
    "load_dataset",
]
