"""Source D — typed contract for the persisted ``discovery/source-d.json``.

Mirrors the pattern established in :mod:`ontozense.core.source_c`: the
extractor pipeline lives elsewhere (here:
``ontozense.core.ingest.source_d``); this module owns the on-disk
contract — dataclasses, serialise/deserialise helpers, and the
file-level builder that re-runs the per-file extractor stages and
captures the IR **before** it is flattened by ``emit_candidates``.

Why capture the IR rather than the IntermediateCandidate stream that
``SourceDIngester`` already produces? ``emit_candidates`` collapses
the rich per-field metadata (``description``, ``is_pk``,
``enum_values``, ``raw_type``, ...) into ``Entity.field``-style flat
labels suitable for the candidate-graph builder. Property extraction
(Phase A) requires the un-flattened metadata so PR2's fusion engine
can build typed ``Attribute`` records. Per Codex round-1 review on
the implementation plan: "Source D persistence must hook before
.../emit.py flattens fields to Entity.field labels, else structure
already lost."

This module is not a parallel extractor — it reuses the exact same
``parse_module`` / ``extract_model`` / ``extract_procedural`` /
``extract_pipeline`` code paths the ingester uses, just collecting
the facts list before the anchor + emit + normalise tail.

Phase A scope (this module):
  - SourceDAttribute / SourceDEntity / SourceDResult dataclasses with
    ``schema_version`` and major-version compatibility check.
  - ``dump_source_d_json`` / ``load_source_d_json`` helpers.
  - ``build_source_d_from_files`` — per-file IR capture, suitable for
    the survey orchestrator.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# JSON schema version for the Source D contract. Bumped when the
# serialised shape changes in a non-backward-compatible way. Mirrors
# the convention used in :mod:`ontozense.core.source_c`.
SCHEMA_VERSION = "1.0"
SUPPORTED_MAJOR_VERSIONS = {"1"}


class SourceDContractError(ValueError):
    """Raised when a Source D JSON file violates the contract.

    Distinct from ``json.JSONDecodeError`` (the file isn't valid JSON
    at all) and ``OSError`` (the file isn't readable). This means the
    JSON parsed but its shape is wrong: unsupported ``schema_version``,
    missing required keys, wrong type for ``entities``, etc.
    """


# ─── Typed contract ──────────────────────────────────────────────────────────


@dataclass
class SourceDAttribute:
    """One attribute (field) of a Source D entity.

    Mirrors the populated set on
    :class:`ontozense.core.ingest.source_d.ir.AttributeFact` after the
    PR1a IR extension, plus the per-attribute provenance (file + line)
    needed for downstream fusion.
    """

    name: str
    raw_type: str = ""                                # ast.unparse(annotation), verbatim
    description: str = ""
    is_multivalued: bool = False
    is_nullable: bool = True
    is_pk: bool = False
    enum_values: list[str] = field(default_factory=list)
    default_factory: str | None = None
    has_default: bool = False
    line: int = 0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_type": self.raw_type,
            "description": self.description,
            "is_multivalued": self.is_multivalued,
            "is_nullable": self.is_nullable,
            "is_pk": self.is_pk,
            "enum_values": list(self.enum_values),
            "default_factory": self.default_factory,
            "has_default": self.has_default,
            "line": self.line,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SourceDAttribute:
        return cls(
            name=raw.get("name", ""),
            raw_type=raw.get("raw_type", ""),
            description=raw.get("description", ""),
            is_multivalued=raw.get("is_multivalued", False),
            is_nullable=raw.get("is_nullable", True),
            is_pk=raw.get("is_pk", False),
            enum_values=list(raw.get("enum_values") or []),
            default_factory=raw.get("default_factory"),
            has_default=raw.get("has_default", False),
            line=raw.get("line", 0),
        )


@dataclass
class SourceDEntity:
    """One Source D entity — a Python class / dataclass / Pydantic
    model / SQLAlchemy 2.0 declarative model — together with the
    AttributeFacts it owns."""

    name: str
    source_file: str = ""
    line: int = 0
    raw_type: str = "class"      # "dataclass" | "pydantic_model" | "dto_candidate" | "sqlalchemy_model" | "class"
    docstring: str = ""
    bases: list[str] = field(default_factory=list)
    attributes: list[SourceDAttribute] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_file": self.source_file,
            "line": self.line,
            "raw_type": self.raw_type,
            "docstring": self.docstring,
            "bases": list(self.bases),
            "attributes": [a.to_json_dict() for a in self.attributes],
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SourceDEntity:
        return cls(
            name=raw.get("name", ""),
            source_file=raw.get("source_file", ""),
            line=raw.get("line", 0),
            raw_type=raw.get("raw_type", "class"),
            docstring=raw.get("docstring", ""),
            bases=list(raw.get("bases") or []),
            attributes=[
                SourceDAttribute.from_json_dict(a)
                for a in raw.get("attributes") or []
            ],
        )


@dataclass
class SourceDResult:
    """The complete Source D contract — entities + their attributes —
    as persisted in ``discovery/source-d.json``."""

    entities: list[SourceDEntity] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    def get_entity(self, name: str) -> SourceDEntity | None:
        for e in self.entities:
            if e.name.lower() == name.lower():
                return e
        return None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_files": list(self.source_files),
            "entities": [e.to_json_dict() for e in self.entities],
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SourceDResult:
        return cls(
            entities=[
                SourceDEntity.from_json_dict(e)
                for e in raw.get("entities") or []
            ],
            source_files=list(raw.get("source_files") or []),
        )


# ─── JSON file helpers ───────────────────────────────────────────────────────


def dump_source_d_json(result: SourceDResult, path: Path) -> None:
    """Serialise a ``SourceDResult`` to JSON. Mirrors
    :func:`ontozense.core.source_c.dump_source_c_json`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_source_d_json(path: Path) -> SourceDResult:
    """Read a Source D JSON file and reconstruct a typed
    ``SourceDResult``. Rejects unknown major schema versions loudly
    (same policy as Source C)."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise SourceDContractError(
            f"Source D JSON root must be an object, got "
            f"{type(raw).__name__}."
        )

    declared_version = raw.get("schema_version", SCHEMA_VERSION)
    if not isinstance(declared_version, str):
        raise SourceDContractError(
            f"schema_version must be a string, got "
            f"{type(declared_version).__name__}."
        )
    declared_major = declared_version.split(".", 1)[0]
    if declared_major not in SUPPORTED_MAJOR_VERSIONS:
        raise SourceDContractError(
            f"Unsupported Source D schema_version {declared_version!r}. "
            f"This Tycho understands major version(s): "
            f"{sorted(SUPPORTED_MAJOR_VERSIONS)}."
        )

    if "entities" not in raw:
        raise SourceDContractError(
            "Source D JSON missing required key 'entities'. The writer "
            "must emit at least an empty list."
        )
    if not isinstance(raw["entities"], list):
        raise SourceDContractError(
            f"Source D JSON 'entities' must be a list, got "
            f"{type(raw['entities']).__name__}."
        )

    return SourceDResult.from_json_dict(raw)


# ─── Builder: extract IR from .py files and project into SourceDResult ──────


def build_source_d_from_files(
    file_paths: Iterable[Path],
    config: dict[str, Any] | None = None,
) -> SourceDResult:
    """Walk a list of ``.py`` files, capture the AttributeFact IR
    before ``emit_candidates`` flattens it, and project the result
    into a typed ``SourceDResult``.

    This is the persistence-side entry point used by the survey
    orchestrator. It re-runs ``parse_module`` and the per-family
    extractors (model / procedural / pipeline) — the same code paths
    :class:`ontozense.core.ingest.ingest_d.SourceDIngester` uses for
    the candidate-graph build — but captures the IR snapshot rather
    than the flattened ``IntermediateCandidate`` stream.

    **Suppression parity (PR1b r1 — Codex blocker 2):** the builder
    mirrors every file-level suppression
    :class:`ontozense.core.ingest.ingest_d.SourceDIngester` applies so
    persistence cannot resurrect files the candidate-graph build
    suppressed:

      - ``config["exclude_paths"]`` — user-suppressed path globs (loaded
        from ``<domain-dir>/source-d.yaml``).
      - :data:`DEFAULT_SOURCE_D_PATH_SUPPRESSIONS` — default path noise
        (``tests/**``, ``fixtures/**``, ``migrations/**``,
        ``**/conftest.py``, ...).
      - :data:`GENERATED_MARKERS` — first-five-lines check for
        ``# DO NOT EDIT`` / ``# Generated by`` / ``# AUTOGENERATED``
        markers.

    ``config`` is also forwarded to ``extract_model`` for the
    ``include_classes`` / ``exclude_classes`` / ``force_vocabulary``
    behaviour the ingester applies inside each parsed file.

    Non-``.py`` paths, suppressed paths, files with generated-code
    markers, and files with parse errors are all silently skipped
    (parse failures logged at WARNING).
    """
    # Local import to avoid circular: ingest.source_d.* imports from
    # ontozense.core.* during package load.
    from .ingest.filters import (
        DEFAULT_SOURCE_D_PATH_SUPPRESSIONS,
        path_match,
    )
    from .ingest.ingest_d import GENERATED_MARKERS
    from .ingest.source_d.dispatch import select_families
    from .ingest.source_d.ir import AttributeFact, EntityFact
    from .ingest.source_d.model_extractor import extract_model
    from .ingest.source_d.parse import parse_module
    from .ingest.source_d.pipeline_extractor import extract_pipeline
    from .ingest.source_d.procedural_extractor import extract_procedural

    config = config or {}
    user_exclude_paths: list[str] = list(config.get("exclude_paths", []) or [])
    entities: list[SourceDEntity] = []
    files_seen: list[str] = []

    for raw_path in file_paths:
        path = Path(raw_path)
        if path.suffix.lower() != ".py":
            continue

        # ── Path-based suppression (PR1b r1) ──────────────────────────
        path_str_norm = str(path).replace("\\", "/")
        if path_match(path_str_norm, user_exclude_paths):
            continue
        if path_match(path_str_norm, DEFAULT_SOURCE_D_PATH_SUPPRESSIONS):
            continue

        # ── Read file (needed for generated-marker check + parse) ─────
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # ── Generated-code marker check (first 5 lines) (PR1b r1) ─────
        first_lines = "\n".join(raw_text.splitlines()[:5])
        if any(marker in first_lines for marker in GENERATED_MARKERS):
            continue

        try:
            pm = parse_module(path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            logger.warning(
                "Source D persistence: skipping %s (%s)", path, exc,
            )
            continue
        files_seen.append(str(path))

        # Collect facts from every family the dispatcher selects, exactly
        # mirroring the ingester. ``config["rule_extractors"]`` honoured.
        families = select_families(pm)
        if "rule_extractors" in config:
            allowed = set(config["rule_extractors"] or [])
            families = [f for f in families if f in allowed]
        facts: list[object] = []
        for fam in families:
            if fam == "model":
                facts.extend(extract_model(pm, config))
            elif fam == "procedural":
                facts.extend(extract_procedural(pm, config))
            else:
                # Other families (e.g. pipeline) may emit AttributeFacts
                # in future; keep the door open.
                fn = {"pipeline": extract_pipeline}.get(fam)
                if fn is not None:
                    facts.extend(fn(pm))

        # Group AttributeFacts under their parent EntityFact. Facts
        # without ``subject_entity`` (free-standing attributes) are
        # dropped here because there's no entity to attach them to in
        # the SourceDResult contract.
        entity_facts = [f for f in facts if isinstance(f, EntityFact)]
        attr_facts = [
            f for f in facts
            if isinstance(f, AttributeFact) and f.subject_entity
        ]

        for ef in entity_facts:
            if ef.suppressed:
                continue
            attrs_for_entity = [
                SourceDAttribute(
                    name=af.name,
                    raw_type=af.raw_type,
                    description=af.description,
                    is_multivalued=af.is_multivalued,
                    is_nullable=af.is_nullable,
                    is_pk=af.is_pk,
                    enum_values=list(af.enum_values),
                    default_factory=af.default_factory,
                    has_default=af.has_default,
                    line=af.evidence_span.start_line,
                )
                for af in attr_facts
                if af.subject_entity == ef.name
            ]
            entities.append(SourceDEntity(
                name=ef.name,
                source_file=ef.evidence_span.file,
                line=ef.evidence_span.start_line,
                raw_type=ef.raw_type,
                docstring=ef.docstring or "",
                bases=list(ef.bases),
                attributes=attrs_for_entity,
            ))

    return SourceDResult(
        entities=entities,
        source_files=files_seen,
    )
