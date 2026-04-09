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
    normalize: bool = typer.Option(False, "--normalize", help="Normalize names for Fabric IQ"),
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
        renames = mgr.normalize_names(fabric_iq=True)
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
