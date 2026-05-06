"""Benchmark metrics + reporting (Phase 7).

Computes a pipeline-health snapshot from a fused output (and
optionally a profile). The point: give the user one place to ask
"is my run any good?" without comparing against a curated reference.

Reference-benchmark mode (precision/recall/F1 vs a gold-standard
dictionary) is intentionally out of scope for this phase — it
requires a reference artifact and is a follow-up. The data shape
here is extensible enough to slot a ``ReferenceComparison`` block in
later without breaking existing consumers.

Six metric sections:

  - **ElementCounts**: total / governance-validated / multi-source /
    by-source-combination breakdown.
  - **ConfidenceStats**: min / median / mean / max + 4-bucket
    histogram + needs-review count.
  - **ConflictStats**: total conflicts, elements-with-at-least-one,
    breakdown by resolution type.
  - **AnchorCoverage** (Phase 6 thread): per-field provenance entries
    with vs without typed FieldAnchor data.
  - **CorroborationStats** (Phase 5 thread): elements with multi-doc
    tracking, doc-count distribution.
  - **ProfileCoverage** (when profile supplied): which entity_types
    and predicates from the profile actually got populated.

Output flows: ``compute_benchmark()`` returns a typed
``BenchmarkReport``; ``render_markdown()`` turns it into a
human-readable digest. The CLI ``ontozense report`` writes JSON
(machine-diffable for run-vs-run comparison) AND markdown (for
review and file-back into the domain knowledge base).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from statistics import mean, median
from typing import Any, Optional

from .fusion import FusedElement, FusionResult
from .profile import Profile


# ─── Per-section dataclasses ────────────────────────────────────────────────


@dataclass
class ElementCounts:
    total: int = 0
    governance_validated: int = 0
    multi_source: int = 0   # elements with ≥2 distinct sources
    by_source_combination: dict[str, int] = field(default_factory=dict)


@dataclass
class ConfidenceStats:
    min: float = 0.0
    median: float = 0.0
    mean: float = 0.0
    max: float = 0.0
    buckets: dict[str, int] = field(default_factory=dict)
    needs_review: int = 0


@dataclass
class ConflictStats:
    total_conflicts: int = 0
    elements_with_conflicts: int = 0
    by_resolution: dict[str, int] = field(default_factory=dict)


@dataclass
class AnchorCoverage:
    total_field_provenance: int = 0
    with_anchor: int = 0           # FieldProvenance.anchor is not None
    with_non_empty_anchor: int = 0  # … and not is_empty()
    by_field: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class CorroborationStats:
    """Phase 5 multi-doc tracking. Counts only elements where
    ``corroborating_doc_count`` is populated (which is profile-mode
    or multi-doc fusion)."""
    elements_tracked: int = 0
    distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class ProfileCoverage:
    entity_types_total: int = 0
    entity_types_covered: int = 0
    entity_types_unused: list[str] = field(default_factory=list)
    predicates_total: int = 0
    predicates_covered: int = 0
    predicates_unused: list[str] = field(default_factory=list)


@dataclass
class BenchmarkReport:
    """The full Phase 7 pipeline-health snapshot."""
    timestamp: str = ""
    sources_used: list[str] = field(default_factory=list)
    profile_name: str = ""
    profile_version: str = ""
    elements: ElementCounts = field(default_factory=ElementCounts)
    confidence: ConfidenceStats = field(default_factory=ConfidenceStats)
    conflicts: ConflictStats = field(default_factory=ConflictStats)
    anchors: AnchorCoverage = field(default_factory=AnchorCoverage)
    corroboration: CorroborationStats = field(
        default_factory=CorroborationStats,
    )
    profile_coverage: Optional[ProfileCoverage] = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly nested dict. ``None`` profile_coverage is
        preserved so consumers can tell "no profile supplied" apart
        from "profile supplied with zero coverage"."""
        return asdict(self)


# ─── Public entry point ──────────────────────────────────────────────────────


def compute_benchmark(
    fusion_result: FusionResult,
    profile: Optional[Profile] = None,
) -> BenchmarkReport:
    """Compute a benchmark snapshot from a fused result.

    The fused result is read-only — this function never mutates it.
    Profile is optional; when supplied, ``profile_coverage`` is filled
    with which declared entity_types and predicates actually got
    populated. Without a profile, that section is ``None``.
    """
    report = BenchmarkReport(
        timestamp=datetime.utcnow().isoformat(),
        sources_used=list(fusion_result.sources_used),
        profile_name=profile.profile_name if profile else "",
        profile_version=profile.profile_version if profile else "",
    )
    report.elements = _compute_element_counts(fusion_result.elements)
    report.confidence = _compute_confidence_stats(fusion_result.elements)
    report.conflicts = _compute_conflict_stats(fusion_result.elements)
    report.anchors = _compute_anchor_coverage(fusion_result.elements)
    report.corroboration = _compute_corroboration_stats(fusion_result.elements)
    if profile is not None:
        report.profile_coverage = _compute_profile_coverage(
            fusion_result, profile,
        )
    return report


# ─── Section computers ──────────────────────────────────────────────────────


def _compute_element_counts(elements: list[FusedElement]) -> ElementCounts:
    counts = ElementCounts(total=len(elements))
    for el in elements:
        sources_key = "+".join(sorted(set(el.sources))) or "(none)"
        counts.by_source_combination[sources_key] = (
            counts.by_source_combination.get(sources_key, 0) + 1
        )
        if el.governance_validated:
            counts.governance_validated += 1
        if len(set(el.sources)) >= 2:
            counts.multi_source += 1
    return counts


def _compute_confidence_stats(elements: list[FusedElement]) -> ConfidenceStats:
    stats = ConfidenceStats(buckets={
        "0.0-0.5": 0,
        "0.5-0.7": 0,
        "0.7-0.9": 0,
        "0.9-1.0": 0,
    })
    if not elements:
        return stats

    confs = [el.confidence for el in elements]
    stats.min = round(min(confs), 3)
    stats.max = round(max(confs), 3)
    stats.mean = round(mean(confs), 3)
    stats.median = round(median(confs), 3)
    for c in confs:
        if c < 0.5:
            stats.buckets["0.0-0.5"] += 1
        elif c < 0.7:
            stats.buckets["0.5-0.7"] += 1
        elif c < 0.9:
            stats.buckets["0.7-0.9"] += 1
        else:
            stats.buckets["0.9-1.0"] += 1
    stats.needs_review = sum(1 for el in elements if el.needs_review())
    return stats


def _compute_conflict_stats(elements: list[FusedElement]) -> ConflictStats:
    stats = ConflictStats()
    for el in elements:
        if el.conflicts:
            stats.elements_with_conflicts += 1
        for c in el.conflicts:
            stats.total_conflicts += 1
            stats.by_resolution[c.resolution] = (
                stats.by_resolution.get(c.resolution, 0) + 1
            )
    return stats


def _compute_anchor_coverage(
    elements: list[FusedElement],
) -> AnchorCoverage:
    """Counts every FieldProvenance entry across all elements; reports
    how many carry typed FieldAnchor data."""
    cov = AnchorCoverage()
    for el in elements:
        for field_name, prov in el.field_provenance.items():
            cov.total_field_provenance += 1
            per_field = cov.by_field.setdefault(
                field_name, {"with_anchor": 0, "without_anchor": 0},
            )
            anchor = getattr(prov, "anchor", None)
            if anchor is not None:
                cov.with_anchor += 1
                per_field["with_anchor"] += 1
                if not anchor.is_empty():
                    cov.with_non_empty_anchor += 1
            else:
                per_field["without_anchor"] += 1
    return cov


def _compute_corroboration_stats(
    elements: list[FusedElement],
) -> CorroborationStats:
    stats = CorroborationStats(distribution={
        "1_doc": 0, "2_docs": 0, "3+_docs": 0,
    })
    for el in elements:
        count = el.extra_fields.get("corroborating_doc_count")
        if count is None:
            continue
        stats.elements_tracked += 1
        if count == 1:
            stats.distribution["1_doc"] += 1
        elif count == 2:
            stats.distribution["2_docs"] += 1
        else:
            stats.distribution["3+_docs"] += 1
    return stats


def _compute_profile_coverage(
    fusion_result: FusionResult,
    profile: Profile,
) -> ProfileCoverage:
    cov = ProfileCoverage(
        entity_types_total=len(profile.entity_types),
        predicates_total=len(profile.predicates),
    )
    # Which declared types were used? Read entity_type from the same
    # spot Phase 4 validation reads it from (extra_fields), since that
    # is how Phase 5 fusion now exposes the upstream id/type.
    used_types = {
        el.extra_fields.get("entity_type", "")
        for el in fusion_result.elements
    }
    used_types.discard("")
    declared_types = set(profile.entity_types.keys())
    cov.entity_types_covered = sum(
        1 for t in declared_types
        if t in used_types or _has_used_subtype(t, used_types, profile)
    )
    cov.entity_types_unused = sorted(
        t for t in declared_types
        if t not in used_types and not _has_used_subtype(t, used_types, profile)
    )

    used_predicates = {
        rel.predicate.lower()
        for rel in fusion_result.relationships
    }
    declared_predicates_lower = {
        p.lower(): p for p in profile.predicates
    }
    cov.predicates_covered = sum(
        1 for p_lower in declared_predicates_lower
        if p_lower in used_predicates
    )
    cov.predicates_unused = sorted(
        canonical for p_lower, canonical in declared_predicates_lower.items()
        if p_lower not in used_predicates
    )
    return cov


def _has_used_subtype(
    parent_type: str,
    used_types: set[str],
    profile: Profile,
) -> bool:
    """A parent type counts as covered if any of its declared subtypes
    appear in the fused output."""
    et = profile.entity_types.get(parent_type)
    if et is None:
        return False
    for sub in et.subtypes:
        if sub in used_types:
            return True
    return False


# ─── Markdown rendering ─────────────────────────────────────────────────────


def render_markdown(report: BenchmarkReport) -> str:
    """Render a BenchmarkReport as a human-readable markdown digest."""
    lines: list[str] = []
    lines.append("# Ontozense Benchmark Report")
    lines.append("")
    lines.append(f"**Generated:** {report.timestamp}")
    lines.append(f"**Sources used:** {', '.join(report.sources_used) or '(none)'}")
    if report.profile_name:
        lines.append(
            f"**Profile:** {report.profile_name} "
            f"v{report.profile_version}"
        )
    lines.append("")

    # ── Element counts ──
    e = report.elements
    lines.append("## Elements")
    lines.append("")
    lines.append(f"- Total: **{e.total}**")
    lines.append(f"- Governance-validated: {e.governance_validated}")
    lines.append(f"- Multi-source (≥2 sources): {e.multi_source}")
    if e.by_source_combination:
        lines.append("")
        lines.append("| Source combination | Count |")
        lines.append("|---|---:|")
        for combo, n in sorted(
            e.by_source_combination.items(),
            key=lambda kv: -kv[1],
        ):
            lines.append(f"| {combo} | {n} |")
    lines.append("")

    # ── Confidence ──
    c = report.confidence
    lines.append("## Confidence")
    lines.append("")
    lines.append(
        f"- min={c.min}, median={c.median}, "
        f"mean={c.mean}, max={c.max}"
    )
    lines.append(f"- Needs review: **{c.needs_review}**")
    if c.buckets:
        lines.append("")
        lines.append("| Bucket | Count |")
        lines.append("|---|---:|")
        for bucket in ["0.0-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0"]:
            lines.append(f"| {bucket} | {c.buckets.get(bucket, 0)} |")
    lines.append("")

    # ── Conflicts ──
    cf = report.conflicts
    lines.append("## Conflicts")
    lines.append("")
    lines.append(f"- Total conflicts: **{cf.total_conflicts}**")
    lines.append(f"- Elements with at least one conflict: {cf.elements_with_conflicts}")
    if cf.by_resolution:
        lines.append("")
        lines.append("| Resolution | Count |")
        lines.append("|---|---:|")
        for res, n in sorted(cf.by_resolution.items()):
            lines.append(f"| {res} | {n} |")
    lines.append("")

    # ── Anchors ──
    a = report.anchors
    lines.append("## Provenance anchors (Phase 6)")
    lines.append("")
    lines.append(f"- Total field-provenance entries: {a.total_field_provenance}")
    lines.append(f"- With FieldAnchor: {a.with_anchor}")
    lines.append(f"- With non-empty anchor: {a.with_non_empty_anchor}")
    if a.by_field:
        lines.append("")
        lines.append("| Field | With anchor | Without |")
        lines.append("|---|---:|---:|")
        for fname in sorted(a.by_field):
            row = a.by_field[fname]
            lines.append(
                f"| {fname} | {row.get('with_anchor', 0)} | "
                f"{row.get('without_anchor', 0)} |"
            )
    lines.append("")

    # ── Corroboration ──
    co = report.corroboration
    lines.append("## Multi-doc corroboration (Phase 5)")
    lines.append("")
    lines.append(f"- Elements with corroboration tracking: {co.elements_tracked}")
    if co.distribution:
        lines.append("")
        lines.append("| Doc count | Elements |")
        lines.append("|---|---:|")
        for label in ["1_doc", "2_docs", "3+_docs"]:
            lines.append(f"| {label} | {co.distribution.get(label, 0)} |")
    lines.append("")

    # ── Profile coverage (optional) ──
    if report.profile_coverage is not None:
        pc = report.profile_coverage
        lines.append("## Profile coverage")
        lines.append("")
        lines.append(
            f"- Entity types covered: "
            f"{pc.entity_types_covered}/{pc.entity_types_total}"
        )
        if pc.entity_types_unused:
            lines.append(
                f"  - Unused: {', '.join(pc.entity_types_unused)}"
            )
        lines.append(
            f"- Predicates covered: "
            f"{pc.predicates_covered}/{pc.predicates_total}"
        )
        if pc.predicates_unused:
            lines.append(
                f"  - Unused: {', '.join(pc.predicates_unused)}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
