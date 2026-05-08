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

from .fusion import FusedElement, FusionResult, normalise_name
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
    # Phase 7 wrap-up: subtype-level coverage. ``subtypes_total``
    # counts every declared subtype across all entity types;
    # ``subtypes_covered`` counts those actually used; ``subtypes_unused``
    # lists the missing ones with their parent for context. A profile
    # without subtypes (entity types declared with no ``subtypes``
    # array) reports zero across all three.
    subtypes_total: int = 0
    subtypes_covered: int = 0
    subtypes_unused: list[str] = field(default_factory=list)
    predicates_total: int = 0
    predicates_covered: int = 0
    predicates_unused: list[str] = field(default_factory=list)


@dataclass
class ReferenceComparison:
    """Tycho 1.0+ wrap-up #3: precision / recall / F1 of the fused
    output against a curated reference dictionary.

    The reference is supplied as a fused-shape JSON file (same shape
    as the fuse output, but with only the canonical truth — typically
    a domain expert's hand-curated data dictionary). Matching key:
    profile-mode ``id`` if both sides have one, else
    ``normalise_name(element_name)``.

    Empty inputs produce all-zero metrics (no division by zero).
    """
    reference_path: str = ""

    # Element-level
    reference_element_total: int = 0
    fused_element_total: int = 0
    elements_true_positive: int = 0
    elements_false_positive: int = 0
    elements_false_negative: int = 0
    elements_precision: float = 0.0
    elements_recall: float = 0.0
    elements_f1: float = 0.0
    missing_elements: list[str] = field(default_factory=list)
    extra_elements: list[str] = field(default_factory=list)

    # Relationship-level (same idea for triples)
    reference_relationship_total: int = 0
    fused_relationship_total: int = 0
    relationships_true_positive: int = 0
    relationships_false_positive: int = 0
    relationships_false_negative: int = 0
    relationships_precision: float = 0.0
    relationships_recall: float = 0.0
    relationships_f1: float = 0.0


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
    reference_comparison: Optional[ReferenceComparison] = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly nested dict. ``None`` profile_coverage and
        reference_comparison are preserved so consumers can tell
        "no profile / reference supplied" apart from "supplied with
        zero coverage"."""
        return asdict(self)


# ─── Public entry point ──────────────────────────────────────────────────────


def compute_benchmark(
    fusion_result: FusionResult,
    profile: Optional[Profile] = None,
    reference: Optional[FusionResult] = None,
    reference_path: str = "",
) -> BenchmarkReport:
    """Compute a benchmark snapshot from a fused result.

    The fused result is read-only — this function never mutates it.

    ``profile`` (optional): when supplied, ``profile_coverage`` is
    filled with which declared entity_types and predicates got
    populated. Without a profile, that section is ``None``.

    ``reference`` (optional, Tycho 1.0+): a fused-shape ``FusionResult``
    representing the curated truth. When supplied, ``reference_comparison``
    holds element- and relationship-level precision / recall / F1.
    Without a reference, that section is ``None`` and AC1 byte-identity
    of the report JSON is preserved (the key is omitted via the
    Optional default).
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
    if reference is not None:
        report.reference_comparison = _compute_reference_comparison(
            fusion_result, reference, reference_path,
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
        # Skip absent (None) and anomalous (<= 0) values. Phase 5
        # fusion never sets a non-positive count — corroboration
        # tracking only fires after at least one doc is appended —
        # but a hand-edited fused JSON could carry one. Silently
        # ignore those rather than mis-bucketing them as ``3+_docs``
        # via the else branch.
        if count is None or not isinstance(count, int) or count <= 0:
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

    # Subtype-level coverage. Iterate every declared subtype across
    # every entity type; a subtype is "covered" when its name appears
    # directly in ``used_types``. Unused subtypes are surfaced with
    # ``parent.subtype`` notation so the reviewer immediately sees
    # which top-level the gap belongs to.
    for parent_name, et in profile.entity_types.items():
        for subtype in et.subtypes:
            cov.subtypes_total += 1
            if subtype in used_types:
                cov.subtypes_covered += 1
            else:
                cov.subtypes_unused.append(f"{parent_name}.{subtype}")
    cov.subtypes_unused.sort()

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


# ─── Reference comparison (wrap-up #3) ──────────────────────────────────────


def _element_match_key(el: FusedElement) -> str:
    """Matching key for an element across fused output and reference.

    Profile mode: match by deterministic id when the element carries
    one (the cross-source ID alignment contract from Phases 1–5).
    Unconstrained: fall back to ``normalise_name(element_name)``.
    """
    eid = el.extra_fields.get("id", "") if el.extra_fields else ""
    if eid:
        return f"id:{eid}"
    return f"name:{normalise_name(el.element_name)}"


def _f1(precision: float, recall: float) -> float:
    """F1 with safe division: returns 0.0 when both P and R are 0."""
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _compute_reference_comparison(
    fusion_result: FusionResult,
    reference: FusionResult,
    reference_path: str,
) -> ReferenceComparison:
    """Compare a fused output against a curated reference dictionary
    and emit element- and relationship-level precision/recall/F1.

    Both inputs are FusionResult-shaped — the reference is loaded
    via the same ``_reconstruct_fusion_result`` path the rest of the
    pipeline uses. Read-only on both inputs (no mutation).
    """
    # ── Elements ──
    fused_keys = {
        _element_match_key(el): el.element_name
        for el in fusion_result.elements
    }
    ref_keys = {
        _element_match_key(el): el.element_name
        for el in reference.elements
    }
    tp = len(fused_keys.keys() & ref_keys.keys())
    fp = len(fused_keys.keys() - ref_keys.keys())
    fn = len(ref_keys.keys() - fused_keys.keys())

    p = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    r = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    cmp = ReferenceComparison(
        reference_path=reference_path,
        reference_element_total=len(reference.elements),
        fused_element_total=len(fusion_result.elements),
        elements_true_positive=tp,
        elements_false_positive=fp,
        elements_false_negative=fn,
        elements_precision=round(p, 3),
        elements_recall=round(r, 3),
        elements_f1=round(_f1(p, r), 3),
        # Sorted lists give deterministic JSON output for run-vs-run
        # diffability — same ranking across runs.
        missing_elements=sorted(
            ref_keys[k] for k in (ref_keys.keys() - fused_keys.keys())
        ),
        extra_elements=sorted(
            fused_keys[k] for k in (fused_keys.keys() - ref_keys.keys())
        ),
    )

    # ── Relationships (subject, predicate, object) triples ──
    def _rel_key(rel) -> tuple[str, str, str]:
        return (
            normalise_name(rel.subject),
            rel.predicate.lower(),
            normalise_name(rel.object),
        )

    fused_rels = {_rel_key(rel) for rel in fusion_result.relationships}
    ref_rels = {_rel_key(rel) for rel in reference.relationships}
    rtp = len(fused_rels & ref_rels)
    rfp = len(fused_rels - ref_rels)
    rfn = len(ref_rels - fused_rels)
    rp = (rtp / (rtp + rfp)) if (rtp + rfp) > 0 else 0.0
    rr = (rtp / (rtp + rfn)) if (rtp + rfn) > 0 else 0.0

    cmp.reference_relationship_total = len(reference.relationships)
    cmp.fused_relationship_total = len(fusion_result.relationships)
    cmp.relationships_true_positive = rtp
    cmp.relationships_false_positive = rfp
    cmp.relationships_false_negative = rfn
    cmp.relationships_precision = round(rp, 3)
    cmp.relationships_recall = round(rr, 3)
    cmp.relationships_f1 = round(_f1(rp, rr), 3)

    return cmp


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
        # Subtype line only emits when the profile actually declares
        # subtypes — keeps the report tidy for profiles that don't.
        if pc.subtypes_total > 0:
            lines.append(
                f"- Subtypes covered: "
                f"{pc.subtypes_covered}/{pc.subtypes_total}"
            )
            if pc.subtypes_unused:
                lines.append(
                    f"  - Unused: {', '.join(pc.subtypes_unused)}"
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

    # ── Reference comparison (optional, wrap-up #3) ──
    if report.reference_comparison is not None:
        rc = report.reference_comparison
        lines.append("## Reference comparison")
        lines.append("")
        if rc.reference_path:
            lines.append(f"**Reference:** `{rc.reference_path}`")
            lines.append("")
        lines.append("| | Precision | Recall | F1 | TP | FP | FN |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        lines.append(
            f"| Elements ({rc.fused_element_total} fused vs "
            f"{rc.reference_element_total} ref) | "
            f"{rc.elements_precision} | {rc.elements_recall} | "
            f"**{rc.elements_f1}** | {rc.elements_true_positive} | "
            f"{rc.elements_false_positive} | "
            f"{rc.elements_false_negative} |"
        )
        lines.append(
            f"| Relationships ({rc.fused_relationship_total} fused vs "
            f"{rc.reference_relationship_total} ref) | "
            f"{rc.relationships_precision} | "
            f"{rc.relationships_recall} | "
            f"**{rc.relationships_f1}** | "
            f"{rc.relationships_true_positive} | "
            f"{rc.relationships_false_positive} | "
            f"{rc.relationships_false_negative} |"
        )
        if rc.missing_elements:
            lines.append("")
            lines.append(
                f"**Missing from fused output ({len(rc.missing_elements)}):** "
                f"{', '.join(rc.missing_elements[:20])}"
                + (" …" if len(rc.missing_elements) > 20 else "")
            )
        if rc.extra_elements:
            lines.append("")
            lines.append(
                f"**Extra in fused output ({len(rc.extra_elements)}):** "
                f"{', '.join(rc.extra_elements[:20])}"
                + (" …" if len(rc.extra_elements) > 20 else "")
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
