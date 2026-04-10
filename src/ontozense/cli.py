"""Ontozense CLI — extract, refine, and export ontologies."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ontozense",
    help="Extract, engineer, and refine ontologies from domain documents.",
    no_args_is_help=True,
)
console = Console()


def _load_env() -> None:
    """Load .env file if present."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


# ─── ingest (router-based dispatch) ───────────────────────────────────────────

@app.command()
def ingest(
    paths: list[Path] = typer.Argument(
        ...,
        help="One or more files or directories to route into the knowledge base.",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help=(
            "Per-domain knowledge base directory. If provided, every routing "
            "decision is logged to <domain-dir>/log.md."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print routing decisions but don't actually run any extractors.",
    ),
    auto: bool = typer.Option(
        False, "--auto",
        help=(
            "Auto-route without human confirmation. By default the router only "
            "prints the decisions; pass --auto to also dispatch them. Per "
            "PLAYBOOK §5, auto-dispatch only fires for routing decisions with "
            "confidence > 0.9. Lower-confidence decisions are listed as "
            "skipped so the human can review them. Currently only Source A "
            "dispatch is wired (other Sources land in later steps)."
        ),
    ),
    auto_threshold: float = typer.Option(
        0.9, "--auto-threshold",
        help=(
            "Confidence gate for --auto dispatch. Routing decisions below "
            "this threshold are listed as skipped instead of dispatched. "
            "Default 0.9 per PLAYBOOK §5."
        ),
    ),
    recursive: bool = typer.Option(
        True, "--recursive/--no-recursive",
        help="Recurse into subdirectories when a directory is given.",
    ),
) -> None:
    """Route incoming files to the right Source extractor.

    The router classifies each file by its extension and content patterns
    into one of:

      - Source A — Authoritative domain documents (prose: PDF, MD, DOCX, ...)
      - Source B — Governance / data dictionaries (Excel, CSV, ...)
      - Source C — Database schemas (DDL, JSON Schema, ...)
      - Source D — Production code (Python, SQL, ...)
      - skip   — Not useful for ontology extraction (README, LICENSE, ...)

    By default, prints the routing decisions but does NOT dispatch them.
    Pass --auto to dispatch. Currently only Source A dispatch is wired
    (Sources B/D and the fusion layer land in later steps).
    """
    _load_env()

    from .router import Router, Source
    from .log import append_log

    router = Router()

    # Collect all decisions across all paths
    decisions = []
    for p in paths:
        if not p.exists():
            console.print(f"[red]Path not found:[/] {p}")
            raise typer.Exit(code=1)
        if p.is_dir():
            decisions.extend(router.route_directory(p, recursive=recursive))
        else:
            decisions.append(router.route(p))

    if not decisions:
        console.print("[yellow]No files to route.[/]")
        return

    # Group by source for the summary
    by_source: dict[str, list] = {}
    for d in decisions:
        key = d.primary_source.value
        by_source.setdefault(key, []).append(d)

    # Print summary
    console.print()
    console.print(f"[bold]Routed {len(decisions)} file(s):[/]")
    for source_key in ("A", "B", "C", "D", "skip"):
        if source_key in by_source:
            count = len(by_source[source_key])
            label = {
                "A": "Source A — Authoritative domain documents",
                "B": "Source B — Governance / data dictionaries",
                "C": "Source C — Database schemas",
                "D": "Source D — Production code",
                "skip": "Skipped (README, license, binary, ...)",
            }[source_key]
            console.print(f"  [cyan]{source_key}[/] — {count} file(s) — {label}")
    console.print()

    # Per-file detail
    for d in decisions:
        primary = d.primary_source.value
        marker = "↓" if d.is_skip else "→"
        sources_str = "+".join(s.value for s in d.sources)
        console.print(
            f"  [bold]{marker}[/] [cyan]{sources_str:>6}[/] "
            f"[dim]({d.confidence:.0%}, {d.layer})[/] "
            f"{d.file_path.name}"
        )
        console.print(f"        [dim]{d.reasoning}[/]")
        if domain_dir:
            append_log(
                domain_dir, "ingest",
                source=d.file_path.name,
                route=primary,
                confidence=f"{d.confidence:.2f}",
                layer=d.layer,
                reasoning=d.reasoning,
            )

    if dry_run:
        console.print()
        console.print("[yellow]Dry run — no extractors invoked.[/]")
        return

    if not auto:
        console.print()
        console.print(
            "[yellow]Routing complete. Pass [bold]--auto[/] to dispatch the "
            "files to their extractors. Currently only Source A dispatch is "
            "wired; Sources B/C/D and the fusion layer land in later steps.[/]"
        )
        return

    # ── Auto-dispatch with confidence gate ──
    # Per PLAYBOOK §5, --auto only dispatches decisions with confidence
    # above the threshold. Lower-confidence decisions are listed as
    # skipped so the human can review them before they run.
    dispatchable = [d for d in decisions if d.confidence > auto_threshold and not d.is_skip]
    low_confidence = [d for d in decisions if d.confidence <= auto_threshold and not d.is_skip]

    if low_confidence:
        console.print()
        console.print(
            f"[yellow]Skipped {len(low_confidence)} low-confidence decision(s) "
            f"(confidence ≤ {auto_threshold:.2f}):[/]"
        )
        for d in low_confidence:
            sources_str = "+".join(s.value for s in d.sources)
            console.print(
                f"  [dim]•[/] [cyan]{sources_str}[/] "
                f"[dim]({d.confidence:.0%})[/] {d.file_path.name}"
            )
            if domain_dir:
                append_log(
                    domain_dir, "ingest-skipped",
                    source=d.file_path.name,
                    route="+".join(s.value for s in d.sources),
                    confidence=f"{d.confidence:.2f}",
                    reason="below_auto_threshold",
                    threshold=f"{auto_threshold:.2f}",
                )

    # ── True multi-source dispatch ──
    # A single decision may list more than one source (e.g. a markdown
    # developer guide is both A and D). We dispatch each source leg
    # independently and log each leg. Currently only Source A is wired;
    # B/C/D legs produce a "not yet implemented" note but are still
    # counted and logged so multi-source is visible in the audit trail.
    buckets: dict[Source, list[Path]] = {
        Source.A: [],
        Source.B: [],
        Source.C: [],
        Source.D: [],
    }
    for d in dispatchable:
        for s in d.sources:
            if s in buckets:
                buckets[s].append(d.file_path)
                if domain_dir:
                    append_log(
                        domain_dir, "ingest-dispatch",
                        source=d.file_path.name,
                        route=s.value,
                        confidence=f"{d.confidence:.2f}",
                        multi_source="yes" if d.is_multi_source else "no",
                    )

    # Source A — wired
    if buckets[Source.A]:
        console.print()
        console.print(
            f"[bold blue]Auto-dispatching {len(buckets[Source.A])} file(s) to "
            f"Source A (extract-a)...[/]"
        )
        extract_a(
            documents=buckets[Source.A],
            output=Path("source-a-extraction.xlsx"),
            json_output=None,
            domain=None,
            domain_dir=domain_dir,
            model="azure/gpt-5.4",
            template=None,
            review_threshold=0.7,
            skip_definitions_pass=False,
        )

    # Sources B/C/D — not yet wired; report per source so the human sees
    # exactly which legs of multi-source decisions were skipped.
    for src in (Source.B, Source.C, Source.D):
        if buckets[src]:
            console.print()
            console.print(
                f"[yellow]{len(buckets[src])} file(s) routed to Source "
                f"{src.value} — auto-dispatch not yet implemented.[/]"
            )
            for fp in buckets[src]:
                console.print(f"  [dim]•[/] {fp.name}")


# ─── extract-a (Source A: domain documents) ───────────────────────────────────

@app.command(name="extract-a")
def extract_a(
    documents: list[Path] = typer.Argument(
        ...,
        help=(
            "One or more authoritative domain documents to extract from "
            "(plain-text formats: .md, .txt). PDF/DOCX must be converted "
            "to text first."
        ),
    ),
    output: Path = typer.Option(
        "source-a-extraction.xlsx",
        "--output", "-o",
        help="Output Excel file (per-source view: Concepts + Relationships sheets)",
    ),
    json_output: Path = typer.Option(
        None, "--json", "-j",
        help="Also save raw extraction as JSON",
    ),
    domain: str = typer.Option(
        None, "--domain", "-d",
        help="Domain name override (otherwise auto-detected from documents)",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help=(
            "Per-domain knowledge base directory. If provided, every "
            "extraction operation appends an audit entry to "
            "<domain-dir>/log.md. The directory is created if missing."
        ),
    ),
    model: str = typer.Option(
        "azure/gpt-5.4", "--model", "-m",
        help=(
            "LiteLLM model identifier. Default is gpt-5.4: it produces "
            "~2.4x more LLM-validated concepts than gpt-5.2 on regulatory "
            "text at the same cost (see PLAYBOOK §12 for the comparison)."
        ),
    ),
    template: Path = typer.Option(
        None, "--template", "-t",
        help="Custom LinkML template (defaults to bundled domain_doc_extraction.yaml)",
    ),
    review_threshold: float = typer.Option(
        0.7, "--review-threshold",
        help="Confidence threshold below which concepts are flagged for review",
    ),
    skip_definitions_pass: bool = typer.Option(
        False, "--skip-definitions-pass",
        help="Skip the regex-based second pass that enriches concepts with definitions",
    ),
) -> None:
    """Extract concepts and relationships from authoritative domain documents (Source A).

    Source A handles any prose-shaped document the domain experts treat as
    canonical: regulations, internal policies, academic papers, vendor specs,
    industry standards, white papers. The extractor uses OntoGPT/SPIRES for
    the LLM call but parses raw_completion_output directly to recover the
    full list (SPIRES's structured parser is lossy for many-items-per-document
    extraction).

    A second regex-based pass (--skip-definitions-pass to disable) finds
    explicit definitional patterns the LLM may have missed and enriches the
    concept list.

    The output is a per-source Excel with Concepts and Relationships sheets.
    The rich 13-field data dictionary is the OUTPUT of the fusion layer
    (Step 6), assembled from all four sources.
    """
    _load_env()

    from .extractors import (
        DomainDocumentExtractor,
        DomainDocumentExtractionResult,
        Concept,
        extract_definitions_from_file,
    )
    from .exporters import DomainDocumentExcelExporter
    from .log import append_log

    extractor = DomainDocumentExtractor(
        model=model,
        template_path=str(template) if template else None,
    )

    # Extract from each document
    results: list[DomainDocumentExtractionResult] = []
    for doc in documents:
        if not doc.exists():
            console.print(f"[red]Document not found:[/] {doc}")
            if domain_dir:
                append_log(
                    domain_dir, "extract-a-failed",
                    source=doc.name, reason="document_not_found",
                )
            raise typer.Exit(code=1)
        console.print(f"[bold blue]Extracting from:[/] {doc}")
        result = extractor.extract_from_file(doc)

        # Optional: enrich with regex-found definitions and add unmatched
        # regex finds as additional regex-only candidate concepts.
        defs_total = 0
        defs_enriched = 0
        regex_only_added = 0
        if not skip_definitions_pass:
            defs_total, defs_enriched, regex_only_added = _enrich_with_definitions(
                result, doc
            )

        if not result.concepts:
            console.print(
                f"  [yellow]⚠ Warning:[/] no concepts extracted from {doc.name}."
            )
            if domain_dir:
                append_log(
                    domain_dir, "extract-a",
                    source=doc.name,
                    concepts=0, relationships=0,
                    warning="zero_concepts",
                )
        else:
            confidence_avg = (
                sum(c.overall_confidence() for c in result.concepts)
                / len(result.concepts)
            )
            llm_count = len(result.concepts) - regex_only_added
            console.print(
                f"  Domain: [cyan]{result.domain_name or 'unspecified'}[/]   "
                f"Concepts: [green]{len(result.concepts)}[/] "
                f"([blue]{llm_count} LLM[/] + [magenta]{regex_only_added} regex[/])   "
                f"Relationships: [green]{len(result.relationships)}[/]   "
                f"Definitions enriched: [magenta]{defs_enriched}/{defs_total}[/]"
            )
            if domain_dir:
                append_log(
                    domain_dir, "extract-a",
                    source=doc.name,
                    domain=result.domain_name or "unspecified",
                    concepts=len(result.concepts),
                    llm_concepts=llm_count,
                    regex_only=regex_only_added,
                    relationships=len(result.relationships),
                    confidence_avg=f"{confidence_avg:.2f}",
                    defs_enriched=defs_enriched,
                    defs_total=defs_total,
                )
        results.append(result)

    # Merge if multiple (placeholder until multi-doc merger is built)
    if len(results) == 1:
        merged = results[0]
    else:
        merged = DomainDocumentExtractionResult(
            domain_name=domain or results[0].domain_name,
            source_documents=[d for r in results for d in r.source_documents],
            extraction_timestamp=results[0].extraction_timestamp,
        )
        for r in results:
            merged.concepts.extend(r.concepts)
            merged.relationships.extend(r.relationships)
            merged.raw_outputs.extend(r.raw_outputs)
        console.print(
            f"[yellow]Note:[/] simple concatenation merge — multi-doc merger "
            f"with conflict detection is a separate planned step. Got "
            f"{len(merged.concepts)} concepts and {len(merged.relationships)} "
            f"relationships in total."
        )
        if domain_dir:
            append_log(
                domain_dir, "merge",
                sources=len(documents),
                concepts=len(merged.concepts),
                relationships=len(merged.relationships),
                note="concat_placeholder",
            )

    # Override domain if user specified
    if domain:
        merged.domain_name = domain

    # Honest failure mode
    total_concepts = len(merged.concepts)
    total_rels = len(merged.relationships)
    if total_concepts == 0 and total_rels == 0:
        console.print()
        console.print(
            "[bold red]✗ Extraction produced 0 concepts and 0 relationships.[/]\n"
            "  No output written. Possible causes:\n"
            "    • OntoGPT failed silently (check Azure OpenAI credentials in .env)\n"
            "    • The documents contain no definitional content\n"
            "    • The LinkML template is mismatched to the document format\n"
            "  To debug, run OntoGPT directly:\n"
            "    ontogpt extract -i <document> -t <template> -m <model> -O json"
        )
        if domain_dir:
            append_log(
                domain_dir, "extract-a-failed",
                reason="zero_total_output", documents=len(documents),
            )
        raise typer.Exit(code=2)

    # Low-confidence gate — PLAYBOOK §8 says "all elements low confidence
    # → exit code 3". Both concepts AND relationships count as elements.
    # The earlier implementation checked concepts only, which could miss
    # the edge case where concepts are empty but relationships are
    # all-low, or where concepts are all-low and relationships are fine.
    high_conf_concepts = sum(
        1 for c in merged.concepts if c.overall_confidence() >= 0.5
    )
    high_conf_rels = sum(
        1 for r in merged.relationships if r.overall_confidence() >= 0.5
    )
    total_elements = total_concepts + total_rels
    high_conf = high_conf_concepts + high_conf_rels
    if total_elements > 0 and high_conf == 0:
        console.print()
        console.print(
            f"[bold yellow]⚠ All {total_elements} extracted elements "
            f"({total_concepts} concepts + {total_rels} relationships) "
            f"have confidence < 50%.[/]\n"
            "  Output will be written but should be discarded or re-run."
        )
        if domain_dir:
            append_log(
                domain_dir, "extract-a",
                warning="all_low_confidence",
                concepts=total_concepts,
                relationships=total_rels,
                high_conf=0,
            )

    # Export Excel
    DomainDocumentExcelExporter(merged).export(
        output, review_threshold=review_threshold
    )
    console.print(f"[bold green]Excel saved:[/] {output}")

    # Optional JSON
    if json_output:
        import json
        from dataclasses import asdict

        # Dataclass dict + injected overall_confidence and needs_review per item.
        # Methods don't serialize via asdict(), so we compute them here.
        out = asdict(merged)
        for raw_concept, concept in zip(out["concepts"], merged.concepts):
            raw_concept["overall_confidence"] = round(concept.overall_confidence(), 3)
            raw_concept["needs_review"] = concept.needs_review(threshold=review_threshold)
        for raw_rel, rel in zip(out["relationships"], merged.relationships):
            raw_rel["overall_confidence"] = round(rel.overall_confidence(), 3)

        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(out, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[bold green]JSON saved:[/] {json_output}")

    # Console summary
    console.print()
    console.print(f"[bold]Concepts:[/] {total_concepts}")
    console.print(
        f"  [green]high (≥80%)[/]: {sum(1 for c in merged.concepts if c.overall_confidence() >= 0.8)}   "
        f"[yellow]mid (50-79%)[/]: {sum(1 for c in merged.concepts if 0.5 <= c.overall_confidence() < 0.8)}   "
        f"[red]low (<50%)[/]: {sum(1 for c in merged.concepts if c.overall_confidence() < 0.5)}"
    )
    console.print(f"[bold]Relationships:[/] {total_rels}")
    console.print(
        f"  [green]high (≥80%)[/]: {sum(1 for r in merged.relationships if r.overall_confidence() >= 0.8)}   "
        f"[yellow]mid (50-79%)[/]: {sum(1 for r in merged.relationships if 0.5 <= r.overall_confidence() < 0.8)}   "
        f"[red]low (<50%)[/]: {sum(1 for r in merged.relationships if r.overall_confidence() < 0.5)}"
    )

    if total_elements > 0 and high_conf == 0:
        raise typer.Exit(code=3)


def _enrich_with_definitions(result, doc: Path) -> tuple[int, int, int]:
    """Run the regex-based definitions extractor and enrich/extend the concept list.

    Two-phase merge:
      1. Enrich existing LLM concepts that have empty definitions, by matching
         their name to a regex-found term. Existing concepts retain their
         high LLM confidence and only the definition is added.
      2. For regex-found terms that DON'T match any LLM concept, add them as
         new ``Concept`` objects with confidence 0.6 and reason ``regex_only``.
         These are clearly distinguishable from LLM-extracted concepts in the
         Excel output (lower confidence band → yellow/red color coding).

    Returns:
        (total_definitions_found, llm_concepts_enriched, regex_only_added)
    """
    from .extractors import extract_definitions_from_file
    from .extractors.domain_doc_extractor import (
        Concept,
        FieldConfidence,
        Provenance,
    )
    from datetime import datetime

    matches = extract_definitions_from_file(doc)
    if not matches:
        return 0, 0, 0

    # Build a lookup by normalized term name
    def_lookup: dict[str, object] = {}
    for m in matches:
        key = m.term.lower().strip()
        if key and key not in def_lookup:
            def_lookup[key] = m

    # Phase 1: enrich existing LLM concepts with empty definitions
    enriched = 0
    matched_terms: set[str] = set()
    llm_concept_keys: set[str] = {c.name.lower().strip() for c in result.concepts}

    for concept in result.concepts:
        key = concept.name.lower().strip()
        # Try exact name match
        if key in def_lookup:
            matched_terms.add(key)
            if not concept.definition:
                m = def_lookup[key]
                concept.definition = m.definition
                concept.confidence.append(
                    FieldConfidence("definition", 0.85, "regex_pattern")
                )
                if not concept.citation and m.source_section:
                    concept.citation = m.source_section
                enriched += 1
            continue
        # Try substring match (LLM concept name contains a regex term, or vice versa)
        for term, m in def_lookup.items():
            if term in key or key in term:
                matched_terms.add(term)
                if not concept.definition:
                    concept.definition = m.definition
                    concept.confidence.append(
                        FieldConfidence("definition", 0.75, "regex_partial")
                    )
                    enriched += 1
                break

    # Phase 2: add regex-found terms that DON'T match any LLM concept as
    # new concepts at LOW confidence ("regex_only" candidates for human
    # review). The confidence is intentionally low (0.4) so they show up
    # in the red band of the Excel — clearly distinguished from LLM-extracted
    # concepts and unambiguously flagged as needing review. They passed
    # pattern matching but not LLM judgment.
    regex_only_added = 0
    for term_key, m in def_lookup.items():
        if term_key in matched_terms:
            continue
        # Skip if this term overlaps any existing LLM concept (substring match)
        if any(term_key in k or k in term_key for k in llm_concept_keys):
            continue
        # Add as a regex-only candidate concept
        new_concept = Concept(name=m.term, definition=m.definition)
        new_concept.confidence.append(
            FieldConfidence("name", 0.4, "regex_only")
        )
        new_concept.confidence.append(
            FieldConfidence("definition", 0.4, "regex_only")
        )
        new_concept.citation = m.source_section
        new_concept.provenance = Provenance(
            source_document=str(doc),
            source_section=m.source_section,
            source_text_snippet=m.definition[:200],
            extraction_timestamp=datetime.utcnow().isoformat(),
        )
        result.concepts.append(new_concept)
        regex_only_added += 1

    return len(matches), enriched, regex_only_added


# ─── extract ──────────────────────────────────────────────────────────────────

@app.command()
def extract(
    input: Path = typer.Argument(..., help="Path to the domain document (MD, TXT, PDF)"),
    output: Path = typer.Option("extracted.owl", "--output", "-o", help="Output OWL file path"),
    model: str = typer.Option("azure/gpt-5.2", "--model", "-m", help="LiteLLM model identifier"),
    template: Path = typer.Option(None, "--template", "-t", help="Custom LinkML template YAML"),
    json_output: Path = typer.Option(None, "--json", "-j", help="Also export Playground JSON"),
    name: str = typer.Option(None, "--name", "-n", help="Ontology name"),
) -> None:
    """Extract an ontology from a domain document using OntoGPT."""
    _load_env()

    from .extractors import OntoGPTExtractor
    from .exporters import PlaygroundExporter

    console.print(f"[bold blue]Extracting ontology from:[/] {input}")

    extractor = OntoGPTExtractor(
        model=model,
        template_path=str(template) if template else None,
    )
    result = extractor.extract_from_file(input)

    console.print(f"  Concepts: {len(result.concepts)}")
    console.print(f"  Relationships: {len(result.relationships)}")

    # Convert to OWL
    mgr = extractor.to_manager(result, base_uri=f"http://ontozense.org/{name or input.stem}#")
    mgr.save(str(output))
    console.print(f"[bold green]OWL saved:[/] {output}")

    # Optionally export Playground JSON
    if json_output:
        exporter = PlaygroundExporter(mgr)
        exporter.save(str(json_output), name=name)
        console.print(f"[bold green]Playground JSON saved:[/] {json_output}")


# ─── convert ──────────────────────────────────────────────────────────────────

@app.command()
def convert(
    input: Path = typer.Argument(..., help="Path to an existing extraction JSON (OntoGPT combined output)"),
    output: Path = typer.Option("ontology.json", "--output", "-o", help="Output Playground JSON path"),
    owl_output: Path = typer.Option(None, "--owl", help="Also save as OWL"),
    name: str = typer.Option(None, "--name", "-n", help="Ontology name"),
) -> None:
    """Convert an existing OntoGPT extraction JSON to Playground format."""
    _load_env()

    from .extractors.ontogpt_extractor import load_existing_extraction, OntoGPTExtractor
    from .exporters import PlaygroundExporter

    console.print(f"[bold blue]Loading extraction:[/] {input}")
    result = load_existing_extraction(input)

    console.print(f"  Concepts: {len(result.concepts)}")
    console.print(f"  Relationships: {len(result.relationships)}")

    extractor = OntoGPTExtractor()
    mgr = extractor.to_manager(result, base_uri=f"http://ontozense.org/{name or input.stem}#")

    # Export Playground JSON
    exporter = PlaygroundExporter(mgr)
    exporter.save(str(output), name=name)
    console.print(f"[bold green]Playground JSON saved:[/] {output}")

    if owl_output:
        mgr.save(str(owl_output))
        console.print(f"[bold green]OWL saved:[/] {owl_output}")


# ─── refine ───────────────────────────────────────────────────────────────────

@app.command()
def refine(
    input: Path = typer.Argument(..., help="Path to OWL ontology file"),
    output: Path = typer.Option(None, "--output", "-o", help="Output path (defaults to overwrite input)"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Run validation"),
    normalize: bool = typer.Option(False, "--normalize", help="Normalize names per a naming policy (Fabric IQ by default)"),
    deduplicate: bool = typer.Option(False, "--deduplicate", help="Find and report duplicate classes"),
    reason: bool = typer.Option(False, "--reason", help="Apply RDFS reasoning"),
) -> None:
    """Refine an OWL ontology — validate, normalize, deduplicate, reason."""
    from .core import OntologyManager

    console.print(f"[bold blue]Loading ontology:[/] {input}")
    mgr = OntologyManager()
    mgr.load(str(input))
    stats = mgr.get_statistics()
    console.print(f"  Classes: {stats['classes']}, Object props: {stats['object_properties']}, "
                  f"Data props: {stats['data_properties']}, Triples: {stats['total_triples']}")

    if validate:
        issues = mgr.validate()
        if issues:
            table = Table(title="Validation Issues")
            table.add_column("Severity", style="bold")
            table.add_column("Subject")
            table.add_column("Message")
            for issue in issues:
                color = {"error": "red", "warning": "yellow", "info": "blue"}.get(issue.severity, "white")
                table.add_row(f"[{color}]{issue.severity}[/]", issue.subject or "", issue.message)
            console.print(table)
        else:
            console.print("[bold green]No validation issues found.[/]")

    if normalize:
        from .core.manager import FABRIC_IQ_POLICY
        renames = mgr.normalize_names(naming_policy=FABRIC_IQ_POLICY)
        if renames:
            console.print(f"[yellow]Normalized {len(renames)} names:[/]")
            for old, new in renames.items():
                console.print(f"  {old} → {new}")

    if deduplicate:
        dupes = mgr.find_duplicates()
        if dupes:
            console.print("[yellow]Potential duplicates found:[/]")
            for a, b, score in dupes:
                console.print(f"  {a} ↔ {b} (similarity: {score:.0%})")
        else:
            console.print("[green]No duplicates found.[/]")

    if reason:
        new_triples = mgr.apply_reasoning("rdfs")
        console.print(f"[blue]Reasoning inferred {new_triples} new triples.[/]")

    out_path = output or input
    mgr.save(str(out_path))
    console.print(f"[bold green]Saved:[/] {out_path}")


# ─── export ───────────────────────────────────────────────────────────────────

@app.command(name="export")
def export_cmd(
    input: Path = typer.Argument(..., help="Path to OWL ontology file"),
    output: Path = typer.Option("ontology.json", "--output", "-o", help="Output Playground JSON path"),
    name: str = typer.Option(None, "--name", "-n", help="Ontology name override"),
    description: str = typer.Option(None, "--description", "-d", help="Ontology description override"),
) -> None:
    """Export an OWL ontology to Ontology Playground JSON format."""
    from .core import OntologyManager
    from .exporters import PlaygroundExporter

    console.print(f"[bold blue]Loading ontology:[/] {input}")
    mgr = OntologyManager()
    mgr.load(str(input))

    exporter = PlaygroundExporter(mgr)
    exporter.save(str(output), name=name, description=description)

    data = exporter.export(name=name, description=description)
    console.print(f"[bold green]Exported:[/] {output}")
    ont = data["ontology"]
    console.print(f"  Entities: {len(ont['entityTypes'])}, Relationships: {len(ont['relationships'])}")


# ─── diff ─────────────────────────────────────────────────────────────────────

@app.command()
def diff(
    file_a: Path = typer.Argument(..., help="First OWL ontology"),
    file_b: Path = typer.Argument(..., help="Second OWL ontology"),
) -> None:
    """Compare two OWL ontologies and show differences."""
    from .core import OntologyManager

    mgr_a = OntologyManager()
    mgr_a.load(str(file_a))
    mgr_b = OntologyManager()
    mgr_b.load(str(file_b))

    result = mgr_a.diff(mgr_b)

    console.print(f"[bold]Diff:[/] {result.summary}")
    if result.added_classes:
        console.print(f"[green]+ Classes:[/] {', '.join(result.added_classes)}")
    if result.removed_classes:
        console.print(f"[red]- Classes:[/] {', '.join(result.removed_classes)}")
    if result.added_properties:
        console.print(f"[green]+ Properties:[/] {', '.join(result.added_properties)}")
    if result.removed_properties:
        console.print(f"[red]- Properties:[/] {', '.join(result.removed_properties)}")
    console.print(f"  Triples: +{result.added_triples} / -{result.removed_triples}")


# ─── info ─────────────────────────────────────────────────────────────────────

@app.command()
def info(
    input: Path = typer.Argument(..., help="Path to OWL ontology file"),
) -> None:
    """Show statistics and metadata for an OWL ontology."""
    from .core import OntologyManager

    mgr = OntologyManager()
    mgr.load(str(input))

    stats = mgr.get_statistics()
    console.print(f"[bold]{input.name}[/]")
    console.print(f"  Classes:           {stats['classes']}")
    console.print(f"  Object properties: {stats['object_properties']}")
    console.print(f"  Data properties:   {stats['data_properties']}")
    console.print(f"  Total triples:     {stats['total_triples']}")

    classes = mgr.get_classes()
    if classes:
        table = Table(title="Classes")
        table.add_column("Name")
        table.add_column("Label")
        table.add_column("Parents")
        for cls in classes:
            table.add_row(cls["name"], cls["label"], ", ".join(cls["parents"]) or "—")
        console.print(table)


if __name__ == "__main__":
    app()
