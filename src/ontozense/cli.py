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


# ─── extract-dd ───────────────────────────────────────────────────────────────

@app.command(name="extract-dd")
def extract_dd(
    documents: list[Path] = typer.Argument(
        ...,
        help=(
            "One or more documents to extract from. Currently supported: "
            "plain-text formats (.md, .txt). PDF/DOCX must be converted to "
            "text first; provenance and confidence scoring rely on a readable "
            "source text file."
        ),
    ),
    output: Path = typer.Option(
        "data-dictionary.xlsx",
        "--output", "-o",
        help="Output Excel file path",
    ),
    json_output: Path = typer.Option(
        None, "--json", "-j",
        help="Also save raw extraction as JSON",
    ),
    gap_report: Path = typer.Option(
        None, "--gap-report", "-g",
        help="Also save gap report as markdown",
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
        "azure/gpt-5.2", "--model", "-m",
        help="LiteLLM model identifier",
    ),
    template: Path = typer.Option(
        None, "--template", "-t",
        help="Custom LinkML template (defaults to bundled data_dictionary.yaml)",
    ),
    review_threshold: float = typer.Option(
        0.7, "--review-threshold",
        help="Confidence threshold below which elements are flagged for review",
    ),
) -> None:
    """Extract a data dictionary from one or more domain documents (Pass 1).

    Uses OntoGPT/SPIRES with the data dictionary template to produce
    Excel output (standard data dictionary column layout), plus a gap
    report showing what needs human review.
    """
    _load_env()

    from .extractors import DataDictionaryExtractor, DataDictionaryResult
    from .exporters import (
        DataDictionaryExcelExporter,
        generate_gap_report,
        render_to_console,
        save_markdown,
    )
    from .log import append_log

    extractor = DataDictionaryExtractor(
        model=model,
        template_path=str(template) if template else None,
    )

    # Extract from each document
    results = []
    for doc in documents:
        if not doc.exists():
            console.print(f"[red]Document not found:[/] {doc}")
            if domain_dir:
                append_log(
                    domain_dir,
                    "extract-dd-failed",
                    source=doc.name,
                    reason="document_not_found",
                )
            raise typer.Exit(code=1)
        console.print(f"[bold blue]Extracting from:[/] {doc}")
        result = extractor.extract_from_file(doc)
        if not result.elements:
            console.print(
                f"  [yellow]⚠ Warning:[/] no data elements extracted from {doc.name}. "
                f"The document may not contain structured field definitions, "
                f"or the LLM extraction may have failed silently."
            )
            if domain_dir:
                append_log(
                    domain_dir,
                    "extract-dd",
                    source=doc.name,
                    elements=0,
                    warning="zero_elements",
                )
        else:
            confidence_avg = (
                sum(el.overall_confidence() for el in result.elements)
                / len(result.elements)
            )
            console.print(
                f"  Domain: [cyan]{result.domain_name or 'unspecified'}[/]   "
                f"Elements: [green]{len(result.elements)}[/]"
            )
            if domain_dir:
                append_log(
                    domain_dir,
                    "extract-dd",
                    source=doc.name,
                    domain=result.domain_name or "unspecified",
                    elements=len(result.elements),
                    confidence_avg=f"{confidence_avg:.2f}",
                )
        results.append(result)

    # Merge if multiple (placeholder until Phase 2 merger is built)
    if len(results) == 1:
        merged = results[0]
    else:
        merged = DataDictionaryResult(
            domain_name=domain or results[0].domain_name,
            source_documents=[d for r in results for d in r.source_documents],
            extraction_timestamp=results[0].extraction_timestamp,
        )
        for r in results:
            merged.elements.extend(r.elements)
        console.print(
            f"[yellow]Note:[/] simple concatenation merge — Phase 2 merger "
            f"will add conflict detection. Got {len(merged.elements)} total elements."
        )

    # Override domain if user specified
    if domain:
        merged.domain_name = domain

    # If we merged multiple documents, record that as a separate operation.
    if len(documents) > 1 and domain_dir:
        append_log(
            domain_dir,
            "merge",
            sources=len(documents),
            elements=len(merged.elements),
            note="concat_placeholder",
        )

    # Honest failure mode: refuse to write a "successful" output if the
    # extraction produced nothing or only low-confidence garbage.
    total_elements = len(merged.elements)
    if total_elements == 0:
        console.print()
        console.print(
            "[bold red]✗ Extraction produced 0 data elements.[/]\n"
            "  No output written. Possible causes:\n"
            "    • OntoGPT failed silently (check Azure OpenAI credentials in .env)\n"
            "    • The documents contain no structured field definitions\n"
            "    • The LinkML template is mismatched to the document format\n"
            "  To debug, run OntoGPT directly:\n"
            "    ontogpt extract -i <document> -t <template> -m <model> -O json"
        )
        if domain_dir:
            append_log(
                domain_dir,
                "extract-dd-failed",
                reason="zero_total_elements",
                documents=len(documents),
            )
        raise typer.Exit(code=2)

    high_conf_count = sum(
        1 for el in merged.elements if el.overall_confidence() >= 0.5
    )
    if high_conf_count == 0:
        console.print()
        console.print(
            f"[bold yellow]⚠ All {total_elements} extracted elements have confidence < 50%.[/]\n"
            "  This usually means the LLM hallucinated content not present in the source.\n"
            "  Output will be written but should be discarded or re-run."
        )
        if domain_dir:
            append_log(
                domain_dir,
                "extract-dd",
                warning="all_low_confidence",
                elements=total_elements,
                high_conf=0,
            )
        # Still write the output (so the user can inspect what was extracted)
        # but exit with a non-zero code so scripts know it's not trustworthy.
        # Continue to write — the human review workflow needs to see the bad data.

    # Export Excel
    DataDictionaryExcelExporter(merged).export(
        output, review_threshold=review_threshold
    )
    console.print(f"[bold green]Excel saved:[/] {output}")

    # Optional JSON
    if json_output:
        import json
        from dataclasses import asdict
        json_output.write_text(
            json.dumps(asdict(merged), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[bold green]JSON saved:[/] {json_output}")

    # Gap report
    report = generate_gap_report(merged, review_threshold=review_threshold)
    render_to_console(report, console)

    if gap_report:
        save_markdown(report, gap_report)
        console.print(f"[bold green]Gap report saved:[/] {gap_report}")

    # Final exit code reflects extraction quality. Scripts can rely on this.
    if high_conf_count == 0:
        raise typer.Exit(code=3)  # all elements low-confidence


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
        "azure/gpt-5.2", "--model", "-m",
        help="LiteLLM model identifier",
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

        # Optional: enrich with regex-found definitions for concepts the LLM
        # may have left empty.
        defs_added = 0
        defs_total = 0
        if not skip_definitions_pass:
            defs_total, defs_added = _enrich_with_definitions(result, doc)

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
            console.print(
                f"  Domain: [cyan]{result.domain_name or 'unspecified'}[/]   "
                f"Concepts: [green]{len(result.concepts)}[/]   "
                f"Relationships: [green]{len(result.relationships)}[/]   "
                f"Definitions enriched: [magenta]{defs_added}/{defs_total}[/]"
            )
            if domain_dir:
                append_log(
                    domain_dir, "extract-a",
                    source=doc.name,
                    domain=result.domain_name or "unspecified",
                    concepts=len(result.concepts),
                    relationships=len(result.relationships),
                    confidence_avg=f"{confidence_avg:.2f}",
                    defs_enriched=defs_added,
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

    high_conf = sum(
        1 for c in merged.concepts if c.overall_confidence() >= 0.5
    )
    if total_concepts > 0 and high_conf == 0:
        console.print()
        console.print(
            f"[bold yellow]⚠ All {total_concepts} extracted concepts have "
            f"confidence < 50%.[/]\n"
            "  Output will be written but should be discarded or re-run."
        )
        if domain_dir:
            append_log(
                domain_dir, "extract-a",
                warning="all_low_confidence",
                concepts=total_concepts, high_conf=0,
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
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(asdict(merged), indent=2, default=str, ensure_ascii=False),
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

    if total_concepts > 0 and high_conf == 0:
        raise typer.Exit(code=3)


def _enrich_with_definitions(result, doc: Path) -> tuple[int, int]:
    """Run the regex-based definitions extractor and enrich existing concepts.

    Returns ``(total_definitions_found, concepts_enriched)``.
    """
    from .extractors import extract_definitions_from_file
    from .extractors.domain_doc_extractor import FieldConfidence

    matches = extract_definitions_from_file(doc)
    if not matches:
        return 0, 0

    # Build a lookup by normalized term
    def_lookup = {}
    for m in matches:
        key = m.term.lower().strip()
        if key and key not in def_lookup:
            def_lookup[key] = m

    enriched = 0
    for concept in result.concepts:
        if concept.definition:
            continue
        # Try exact name match (case-insensitive)
        key = concept.name.lower().strip()
        if key in def_lookup:
            concept.definition = def_lookup[key].definition
            concept.confidence.append(
                FieldConfidence("definition", 0.85, "regex_pattern")
            )
            if not concept.citation and def_lookup[key].source_section:
                concept.citation = def_lookup[key].source_section
            enriched += 1
            continue
        # Try matching by definition text containment
        for term, m in def_lookup.items():
            if term and term in key:
                concept.definition = m.definition
                concept.confidence.append(
                    FieldConfidence("definition", 0.75, "regex_partial")
                )
                enriched += 1
                break

    return len(matches), enriched


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
