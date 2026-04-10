"""Gap report exporter — surfaces what was extracted vs what needs human review.

The honest output of an extraction pipeline. Tells the expert exactly which
fields were filled, which weren't, and which have low confidence — so the
human knows where to spend their review time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..extractors.dd_extractor import (
    DATA_ELEMENT_FIELDS,
    DataDictionaryResult,
    DataElement,
)


@dataclass
class GapReport:
    """Summary of extraction quality and coverage gaps."""
    domain_name: str = ""
    total_elements: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    needs_review: int = 0
    coverage_by_field: list[tuple[str, float, int, int]] = field(default_factory=list)
    elements_below_threshold: list[DataElement] = field(default_factory=list)
    merge_conflict_count: int = 0
    suggested_actions: list[str] = field(default_factory=list)


def compute_coverage(
    result: DataDictionaryResult,
) -> list[tuple[str, float, int, int]]:
    """Compute % of elements that have each field populated.

    Returns: list of (field_name, percentage, filled_count, empty_count)
    """
    if not result.elements:
        return []

    coverage = []
    total = len(result.elements)
    for field_name in DATA_ELEMENT_FIELDS:
        filled = sum(
            1 for el in result.elements
            if getattr(el, field_name, "")
        )
        empty = total - filled
        pct = filled / total if total > 0 else 0.0
        coverage.append((field_name, pct, filled, empty))
    return coverage


def generate_gap_report(
    result: DataDictionaryResult,
    review_threshold: float = 0.7,
) -> GapReport:
    """Build a GapReport from a DataDictionaryResult."""
    report = GapReport(
        domain_name=result.domain_name,
        total_elements=len(result.elements),
    )

    for el in result.elements:
        conf = el.overall_confidence()
        if conf >= 0.8:
            report.high_confidence += 1
        elif conf >= 0.5:
            report.medium_confidence += 1
        else:
            report.low_confidence += 1

        if el.needs_review(threshold=review_threshold):
            report.needs_review += 1
            report.elements_below_threshold.append(el)

        report.merge_conflict_count += len(el.merge_conflicts)

    report.coverage_by_field = compute_coverage(result)

    # Suggested actions
    if report.low_confidence > 0:
        report.suggested_actions.append(
            f"Review {report.low_confidence} low-confidence elements first"
        )
    if report.merge_conflict_count > 0:
        report.suggested_actions.append(
            f"Resolve {report.merge_conflict_count} merge conflicts"
        )
    for field_name, pct, _filled, empty in report.coverage_by_field:
        if pct < 0.3 and empty > 0:
            report.suggested_actions.append(
                f"Field '{field_name}' is sparse ({pct:.0%}) — consider extracting from additional sources"
            )

    return report


# ─── Output formatters ───────────────────────────────────────────────────────

def render_to_console(report: GapReport, console: Console | None = None) -> None:
    """Print a nicely formatted gap report to the terminal."""
    if console is None:
        console = Console()

    console.print()
    console.print(f"[bold cyan]Gap Report — {report.domain_name or 'Unspecified Domain'}[/]")
    console.print()

    summary = Table(title="Extraction Summary", show_header=True, header_style="bold")
    summary.add_column("Metric")
    summary.add_column("Count", justify="right")
    summary.add_row("Total elements", str(report.total_elements))
    summary.add_row("[green]High confidence (≥80%)[/]", str(report.high_confidence))
    summary.add_row("[yellow]Medium confidence (50-79%)[/]", str(report.medium_confidence))
    summary.add_row("[red]Low confidence (<50%)[/]", str(report.low_confidence))
    summary.add_row("[red]Needs human review[/]", str(report.needs_review))
    if report.merge_conflict_count > 0:
        summary.add_row("[red]Merge conflicts[/]", str(report.merge_conflict_count))
    console.print(summary)
    console.print()

    if report.coverage_by_field:
        coverage = Table(title="Field Coverage", show_header=True, header_style="bold")
        coverage.add_column("Field")
        coverage.add_column("% Filled", justify="right")
        coverage.add_column("Filled", justify="right")
        coverage.add_column("Empty", justify="right")
        for field_name, pct, filled, empty in report.coverage_by_field:
            color = "green" if pct >= 0.8 else "yellow" if pct >= 0.5 else "red"
            coverage.add_row(
                field_name,
                f"[{color}]{pct:.0%}[/]",
                str(filled),
                str(empty),
            )
        console.print(coverage)
        console.print()

    if report.suggested_actions:
        console.print("[bold]Suggested actions:[/]")
        for action in report.suggested_actions:
            console.print(f"  • {action}")
        console.print()


def render_to_markdown(report: GapReport) -> str:
    """Render the gap report as a markdown string."""
    lines = []
    lines.append(f"# Gap Report — {report.domain_name or 'Unspecified Domain'}")
    lines.append("")

    lines.append("## Extraction Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Total elements | {report.total_elements} |")
    lines.append(f"| High confidence (≥80%) | {report.high_confidence} |")
    lines.append(f"| Medium confidence (50-79%) | {report.medium_confidence} |")
    lines.append(f"| Low confidence (<50%) | {report.low_confidence} |")
    lines.append(f"| Needs human review | {report.needs_review} |")
    if report.merge_conflict_count > 0:
        lines.append(f"| Merge conflicts | {report.merge_conflict_count} |")
    lines.append("")

    if report.coverage_by_field:
        lines.append("## Field Coverage")
        lines.append("")
        lines.append("| Field | % Filled | Filled | Empty |")
        lines.append("|---|---:|---:|---:|")
        for field_name, pct, filled, empty in report.coverage_by_field:
            lines.append(f"| `{field_name}` | {pct:.0%} | {filled} | {empty} |")
        lines.append("")

    if report.suggested_actions:
        lines.append("## Suggested Actions")
        lines.append("")
        for action in report.suggested_actions:
            lines.append(f"- {action}")
        lines.append("")

    if report.elements_below_threshold:
        lines.append("## Elements Needing Review")
        lines.append("")
        lines.append("| Element | Confidence | Sub-domain | Has Definition |")
        lines.append("|---|---:|---|---|")
        for el in report.elements_below_threshold[:50]:  # cap at 50
            has_def = "Yes" if el.definition else "No"
            lines.append(
                f"| {el.element_name} | {el.overall_confidence():.0%} | "
                f"{el.sub_domain or '—'} | {has_def} |"
            )
        if len(report.elements_below_threshold) > 50:
            lines.append(f"| ... +{len(report.elements_below_threshold) - 50} more | | | |")
        lines.append("")

    return "\n".join(lines)


def save_markdown(report: GapReport, output_path: str | Path) -> Path:
    """Save the gap report as a markdown file."""
    output_path = Path(output_path)
    output_path.write_text(render_to_markdown(report), encoding="utf-8")
    return output_path
