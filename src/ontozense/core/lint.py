"""Lint — periodic consistency check on the fused knowledge base.

Per ``docs/PLAYBOOK.md`` §9, lint is the gap report generalised to
operate on the **fused** knowledge base, not on a single extraction.

Four checks are implemented (MVP):

  1. **Contradictions** — unresolved conflicts between sources
  2. **Orphan terms** — elements not referenced by any relationship
  3. **Undefined but used** — relationship endpoints without a matching element
  4. **Coverage gaps** — elements where important fields are empty

Two checks are deferred:

  - **Stale claims** — requires persistent state across extraction runs
  - **Missing cross-references** — requires domain semantics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .fusion import FusedElement, FusionResult, normalise_name


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class LintFinding:
    """One issue found by the lint checker."""
    category: str      # "contradiction", "orphan", "undefined_used", "coverage_gap"
    severity: str      # "error", "warning", "info"
    element_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LintReport:
    """The result of running lint on a fused knowledge base."""
    findings: list[LintFinding] = field(default_factory=list)
    timestamp: str = ""

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def by_category(self, category: str) -> list[LintFinding]:
        return [f for f in self.findings if f.category == category]

    def by_element(self, name: str) -> list[LintFinding]:
        target = normalise_name(name)
        return [
            f for f in self.findings
            if normalise_name(f.element_name) == target
        ]


# ─── Core fields that coverage-gap checks against ───────────────────────────

# These are the fields we consider "important" for coverage purposes.
# An element missing one of these gets a coverage_gap finding.
CORE_FIELDS = ["definition", "citation"]


# ─── Lint engine ─────────────────────────────────────────────────────────────


def lint(result: FusionResult) -> LintReport:
    """Run all lint checks on a fused knowledge base."""
    report = LintReport(timestamp=datetime.utcnow().isoformat())

    _check_contradictions(result, report)
    _check_orphan_terms(result, report)
    _check_undefined_used(result, report)
    _check_coverage_gaps(result, report)

    return report


def _check_contradictions(result: FusionResult, report: LintReport) -> None:
    """Flag elements with unresolved conflicts between sources."""
    for el in result.elements:
        for conflict in el.conflicts:
            severity = "error" if conflict.resolution == "unresolved" else "warning"
            report.findings.append(
                LintFinding(
                    category="contradiction",
                    severity=severity,
                    element_name=el.element_name,
                    message=(
                        f"Field '{conflict.field_name}': "
                        f"{conflict.winner.source} ({conflict.winner.original_value!r}) "
                        f"vs {', '.join(r.source for r in conflict.rejected)} "
                        f"({', '.join(repr(r.original_value) for r in conflict.rejected)}). "
                        f"Resolved by {conflict.resolution}."
                    ),
                    details={
                        "field": conflict.field_name,
                        "winner_source": conflict.winner.source,
                        "resolution": conflict.resolution,
                    },
                )
            )


def _check_orphan_terms(result: FusionResult, report: LintReport) -> None:
    """Flag elements not mentioned in any relationship (as subject or object)."""
    # Collect all names referenced in relationships
    referenced: set[str] = set()
    for rel in result.relationships:
        referenced.add(normalise_name(rel.subject))
        referenced.add(normalise_name(rel.object))

    for el in result.elements:
        key = normalise_name(el.element_name)
        if key not in referenced and len(result.relationships) > 0:
            report.findings.append(
                LintFinding(
                    category="orphan",
                    severity="info",
                    element_name=el.element_name,
                    message=(
                        f"'{el.element_name}' is not referenced by any "
                        f"relationship (neither as subject nor object)."
                    ),
                )
            )


def _check_undefined_used(result: FusionResult, report: LintReport) -> None:
    """Flag relationship endpoints that have no matching element."""
    element_keys: set[str] = {
        normalise_name(el.element_name) for el in result.elements
    }

    seen: set[str] = set()
    for rel in result.relationships:
        for endpoint_name, role in [
            (rel.subject, "subject"),
            (rel.object, "object"),
        ]:
            key = normalise_name(endpoint_name)
            if key not in element_keys and key not in seen:
                seen.add(key)
                report.findings.append(
                    LintFinding(
                        category="undefined_used",
                        severity="warning",
                        element_name=endpoint_name,
                        message=(
                            f"'{endpoint_name}' appears as a relationship "
                            f"{role} but has no matching element in the "
                            f"fused dictionary."
                        ),
                        details={"role": role},
                    )
                )


def _check_coverage_gaps(result: FusionResult, report: LintReport) -> None:
    """Flag elements missing important fields (definition, citation)."""
    for el in result.elements:
        missing = []
        if not el.definition.strip():
            missing.append("definition")
        if not el.citation.strip():
            missing.append("citation")

        if missing:
            report.findings.append(
                LintFinding(
                    category="coverage_gap",
                    severity="warning" if "definition" in missing else "info",
                    element_name=el.element_name,
                    message=(
                        f"'{el.element_name}' is missing: "
                        f"{', '.join(missing)}. "
                        f"Sources: {'+'.join(el.sources) or 'none'}."
                    ),
                    details={"missing_fields": missing},
                )
            )
