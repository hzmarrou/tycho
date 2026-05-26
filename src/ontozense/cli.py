"""Ontozense CLI — extract, refine, and export ontologies."""

from __future__ import annotations

import glob as _glob
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows so Rich-rendered
    output doesn't crash on cp1252 consoles. Safe no-op on systems
    where stdio is already UTF-8. Called at module import so every
    CLI invocation benefits.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Some environments (e.g. CI capturing streams) refuse to
            # reconfigure. Errors="replace" in the CLI output handlers
            # is our backup.
            pass


_ensure_utf8_stdio()

app = typer.Typer(
    name="ontozense",
    help="Extract, engineer, and refine ontologies from domain documents.",
    no_args_is_help=True,
)
console = Console()


def _load_env() -> None:
    """Load .env file if present, then alias the Azure SDK env-var
    naming convention to LiteLLM's so users with the Azure standard
    ``AZURE_OPENAI_*`` keys don't have to add duplicate ``AZURE_*``
    entries.

    LiteLLM (called via OntoGPT) expects:
      AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION
    while the Azure SDK convention is:
      AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION

    When only the Azure SDK names are set, this function copies their
    values to the LiteLLM names. When both are set, the explicit
    LiteLLM name wins (no clobbering).
    """
    import os
    try:
        from dotenv import find_dotenv, load_dotenv
        # find_dotenv(usecwd=True) walks up from the user's current
        # working directory, not from this module's install location.
        # Without it, editable installs end up loading the source
        # repository's .env instead of the .env next to the user's
        # data, silently hiding provider keys that only live there.
        load_dotenv(find_dotenv(usecwd=True))
    except ImportError:
        pass

    _azure_aliases = {
        "AZURE_API_KEY": "AZURE_OPENAI_API_KEY",
        "AZURE_API_BASE": "AZURE_OPENAI_ENDPOINT",
        "AZURE_API_VERSION": "AZURE_OPENAI_API_VERSION",
    }
    for litellm_name, azure_sdk_name in _azure_aliases.items():
        if not os.environ.get(litellm_name) and os.environ.get(azure_sdk_name):
            os.environ[litellm_name] = os.environ[azure_sdk_name]


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
        marker = "v" if d.is_skip else "->"
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
            f"(confidence <= {auto_threshold:.2f}):[/]"
        )
        for d in low_confidence:
            sources_str = "+".join(s.value for s in d.sources)
            console.print(
                f"  [dim]*[/] [cyan]{sources_str}[/] "
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
                console.print(f"  [dim]*[/] {fp.name}")


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
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Path to a profile directory containing schema.json (and "
            "optional sidecars). Enables ontology-constrained extraction: "
            "the LLM is constrained to the profile's allowed entity types "
            "and predicates, concepts get deterministic IDs, and verbs are "
            "canonicalised. Without this flag, extraction runs unconstrained "
            "(byte-identical to pre-Phase-2 behaviour). See "
            "docs/PROFILE_SPEC.md and docs/profile-examples/esg/."
        ),
    ),
) -> None:
    """Stage 1 power-user command. Most users call `ontozense survey` instead, which runs this and the merge step in one go.

    Extract concepts and relationships from authoritative domain documents (Source A).

    Source A handles any prose-shaped document the domain experts treat as
    canonical: regulations, internal policies, academic papers, vendor specs,
    industry standards, white papers. The extractor uses OntoGPT/SPIRES for
    the LLM call but parses raw_completion_output directly to recover the
    full list (SPIRES's structured parser is lossy for many-items-per-document
    extraction).

    A second regex-based pass (--skip-definitions-pass to disable) finds
    explicit definitional patterns the LLM may have missed and enriches the
    concept list.

    With --profile, runs in constrained mode: the LLM is told the allowed
    entity types/predicates, concepts get deterministic IDs, names are
    canonicalised via the profile's alias_map, and verbs via canonical_verbs.

    The output is a per-source Excel with Concepts and Relationships sheets.
    The rich 17-field data dictionary is the OUTPUT of the fusion layer
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

    # Load profile if requested. Failures are user-facing (clean error,
    # no traceback), per the tester-readiness UX contract. Catch both
    # ProfileError (validation) and OSError (filesystem-level: permission
    # denied, broken symlink, IO error) so neither path leaks a raw
    # traceback to the user.
    loaded_profile = None
    if profile is not None:
        from .core.profile import load_profile, ProfileError
        try:
            loaded_profile = load_profile(profile)
        except ProfileError as e:
            console.print(f"[bold red][x] Profile load failed:[/] {e}")
            console.print(
                "  See docs/PROFILE_SPEC.md for the required schema.json "
                "format, or copy docs/profile-examples/esg/ as a starting "
                "point."
            )
            raise typer.Exit(code=1)
        except OSError as e:
            console.print(
                f"[bold red][x] Profile load failed (filesystem error):[/] "
                f"{type(e).__name__}: {e}"
            )
            console.print(
                f"  Check that the path {profile!s} is readable and that "
                f"all required files (schema.json plus optional sidecars) "
                f"have read permission."
            )
            raise typer.Exit(code=1)

    if loaded_profile is None:
        console.print("[dim]Mode: unconstrained[/]")
    else:
        console.print(
            f"[bold green]Mode: constrained[/] "
            f"(profile={loaded_profile.profile_name}, "
            f"version={loaded_profile.profile_version})"
        )

    extractor = DomainDocumentExtractor(
        model=model,
        template_path=str(template) if template else None,
        profile=loaded_profile,
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
        try:
            result = extractor.extract_from_file(doc)
        except Exception as e:
            # Surface a clean error to the tester instead of a raw
            # traceback. Common causes: Azure auth failure, OntoGPT
            # subprocess error, template not found.
            err_msg = str(e)
            console.print(f"[bold red][x] Extraction failed for {doc.name}[/]")
            console.print(f"  [dim]{type(e).__name__}: {err_msg[:500]}[/]")
            if "api" in err_msg.lower() or "auth" in err_msg.lower() or "credential" in err_msg.lower():
                console.print(
                    "  [yellow]Likely an Azure OpenAI credential issue. "
                    "Check AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION "
                    "in your .env file.[/]"
                )
            elif "ontogpt" in err_msg.lower() or "subprocess" in err_msg.lower():
                console.print(
                    "  [yellow]OntoGPT subprocess failed. Verify 'ontogpt' "
                    "is installed in the active venv: pip show ontogpt[/]"
                )
            elif "template" in err_msg.lower() or "linkml" in err_msg.lower():
                console.print(
                    "  [yellow]LinkML template issue. The default template "
                    "should exist at src/ontozense/templates/[/]"
                )
            if domain_dir:
                append_log(
                    domain_dir, "extract-a-failed",
                    source=doc.name,
                    error=type(e).__name__,
                    message=err_msg[:200],
                )
            raise typer.Exit(code=1)

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
                f"  [yellow][!] Warning:[/] no concepts extracted from {doc.name}."
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
            "[bold red][x] Extraction produced 0 concepts and 0 relationships.[/]\n"
            "  No output written. Possible causes:\n"
            "    * OntoGPT failed silently (check Azure OpenAI credentials in .env)\n"
            "    * The documents contain no definitional content\n"
            "    * The LinkML template is mismatched to the document format\n"
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
            f"[bold yellow][!] All {total_elements} extracted elements "
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
        f"  [green]high (>=80%)[/]: {sum(1 for c in merged.concepts if c.overall_confidence() >= 0.8)}   "
        f"[yellow]mid (50-79%)[/]: {sum(1 for c in merged.concepts if 0.5 <= c.overall_confidence() < 0.8)}   "
        f"[red]low (<50%)[/]: {sum(1 for c in merged.concepts if c.overall_confidence() < 0.5)}"
    )
    console.print(f"[bold]Relationships:[/] {total_rels}")
    console.print(
        f"  [green]high (>=80%)[/]: {sum(1 for r in merged.relationships if r.overall_confidence() >= 0.8)}   "
        f"[yellow]mid (50-79%)[/]: {sum(1 for r in merged.relationships if 0.5 <= r.overall_confidence() < 0.8)}   "
        f"[red]low (<50%)[/]: {sum(1 for r in merged.relationships if r.overall_confidence() < 0.5)}"
    )

    if total_elements > 0 and high_conf == 0:
        raise typer.Exit(code=3)


# ─── suggest-bridges (LLM-suggested bridging for structural gaps) ────────────


@app.command(name="suggest-bridges")
def suggest_bridges_cmd(
    fused_json: Path = typer.Argument(
        ...,
        help="Path to a fused dictionary JSON (output of the fuse command).",
    ),
    output: Path = typer.Option(
        None, "--output", "-o",
        help="Save suggestions as a markdown file (for file-back).",
    ),
    model: str = typer.Option(
        "azure/gpt-5.4", "--model", "-m",
        help="LLM model for litellm (e.g. 'azure/gpt-5.4', 'openai/gpt-4o').",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help="Per-domain knowledge base directory for audit log and auto file-back.",
    ),
    max_gaps: int = typer.Option(
        5, "--max-gaps",
        help="Maximum number of structural gaps to send to the LLM "
             "(worst first by density). Each gap becomes one LLM call. "
             "Default 5 keeps cost bounded.",
    ),
) -> None:
    """Suggest bridging concepts for structural gaps using an LLM.

    First runs structural gap analysis from the lint layer. For each
    gap (up to --max-gaps), constructs a targeted prompt with the two
    disconnected clusters and their definitions, then asks the LLM to
    suggest bridging relationships.

    Each gap triggers one LLM call, so the default cap of 5 gaps keeps
    cost bounded. Raise --max-gaps to explore more gaps; lower it to
    save on LLM calls.

    Output is markdown suitable for ``ontozense file-back``.
    """
    import json
    from .core.lint import _build_concept_graph, _find_structural_holes
    from .core.bridging import suggest_bridges, format_suggestions_markdown
    from .log import append_log

    _load_env()

    if not fused_json.exists():
        console.print(f"[red]File not found:[/] {fused_json}")
        raise typer.Exit(code=1)

    raw = json.loads(fused_json.read_text(encoding="utf-8"))
    fusion_result = _reconstruct_fusion_result(raw)

    # Build graph and find structural holes
    if len(fusion_result.relationships) == 0:
        console.print("[yellow]No relationships in the fused output - "
                      "structural gap analysis requires relationships.[/]")
        raise typer.Exit(code=0)

    G = _build_concept_graph(fusion_result)
    if len(G.nodes) < 3:
        console.print("[yellow]Too few elements for structural analysis.[/]")
        raise typer.Exit(code=0)

    import networkx as nx
    from networkx.algorithms.community import greedy_modularity_communities

    communities = list(greedy_modularity_communities(G))
    holes = _find_structural_holes(G, communities)

    if not holes:
        console.print("[bold green]No structural gaps found - "
                      "the knowledge graph is well-connected.[/]")
        raise typer.Exit(code=0)

    # Sort by severity (worst first) and cap to max_gaps
    holes_sorted = sorted(
        holes,
        key=lambda h: (h[3], -(len(h[0]) + len(h[1]))),
    )
    total_holes = len(holes_sorted)
    holes_to_process = holes_sorted[:max_gaps]

    console.print(
        f"[bold magenta]Found {total_holes} structural gap(s). "
        f"Asking LLM about the worst {len(holes_to_process)} "
        f"({len(holes_to_process)} LLM call(s))...[/]"
    )
    if total_holes > max_gaps:
        console.print(
            f"[dim]{total_holes - max_gaps} additional gap(s) not sent to "
            f"the LLM. Raise --max-gaps to include more.[/]"
        )

    # Build definitions dict for the prompt
    element_definitions = {
        el.element_name: el.definition
        for el in fusion_result.elements
    }

    # Convert capped holes to (community_a, community_b) pairs
    hole_pairs = [(a, b) for a, b, _, _ in holes_to_process]

    try:
        suggestions = suggest_bridges(
            hole_pairs, element_definitions, model=model,
        )
    except Exception as e:
        error_msg = str(e)
        if "auth" in error_msg.lower() or "api" in error_msg.lower():
            console.print(
                f"[red]LLM authentication failed.[/] Check your API key.\n"
                f"  Set AZURE_API_KEY in .env (or the key your model requires).\n"
                f"  Error: {error_msg}"
            )
        else:
            console.print(f"[red]LLM call failed:[/] {error_msg}")
        raise typer.Exit(code=1)

    md = format_suggestions_markdown(suggestions)
    console.print()
    console.print(md)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        console.print(f"[bold green]Saved:[/] {output}")

        if domain_dir:
            from .core.fileback import file_back
            dest = file_back(output, domain_dir, category="analyses")
            console.print(
                f"[bold green]Filed back:[/] {dest.relative_to(domain_dir)}"
            )

    if domain_dir:
        append_log(
            domain_dir, "suggest-bridges",
            source=fused_json.name,
            gaps=len(holes),
            suggestions=len(suggestions),
            model=model,
        )


# ─── query (Step 8: look up elements in fused output) ────────────────────────


@app.command()
def query(
    term: str = typer.Argument(
        ...,
        help="Element name to look up, or a search term to find matching elements.",
    ),
    fused_json: Path = typer.Option(
        ..., "--fused", "-f",
        help="Path to a fused dictionary JSON (output of the fuse command).",
    ),
    output: Path = typer.Option(
        None, "--output", "-o",
        help="Save the query result as a markdown file (for file-back).",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help="Per-domain knowledge base directory. When combined with "
             "--output, automatically files back the result.",
    ),
) -> None:
    """Query the fused data dictionary for an element or search term.

    Looks up a single element by name (exact, case-insensitive) or
    searches for all elements containing the term. Renders a rich
    markdown view showing all fields, sources, conflicts, business
    rules, and relationships.

    With --output, saves the result as a markdown file. With both
    --output and --domain-dir, automatically files it back into
    <domain-dir>/derived/analyses/ and logs the operation.
    """
    import json
    from .core.fusion import (
        FusedElement,
        FusedRelationship,
        FieldConflict,
        FieldProvenance,
        FusionResult,
    )
    from .core.query import query_element, search_elements, render_search_results
    from .log import append_log

    if not fused_json.exists():
        console.print(f"[red]File not found:[/] {fused_json}")
        raise typer.Exit(code=1)

    raw = json.loads(fused_json.read_text(encoding="utf-8"))
    fusion_result = _reconstruct_fusion_result(raw)

    # Try exact lookup first
    md = query_element(fusion_result, term)
    if md is None:
        # Fall back to search
        matches = search_elements(fusion_result, term)
        if not matches:
            console.print(f"[yellow]No elements found matching '{term}'.[/]")
            raise typer.Exit(code=0)
        md = render_search_results(matches, term, fusion_result)

    console.print(md)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        console.print(f"\n[bold green]Saved:[/] {output}")

        # Auto file-back if domain-dir is also provided
        if domain_dir:
            from .core.fileback import file_back
            dest = file_back(output, domain_dir, category="analyses")
            console.print(
                f"[bold green]Filed back:[/] {dest.relative_to(domain_dir)}"
            )


# ─── file-back (Step 8: save derived artifact) ──────────────────────────────


@app.command(name="file-back")
def file_back_cmd(
    source_file: Path = typer.Argument(
        ...,
        help="The file to file back (markdown, CSV, Excel, ...).",
    ),
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help="Per-domain knowledge base directory.",
    ),
    category: str = typer.Option(
        "analyses", "--category",
        help="Sub-directory under derived/ (default: 'analyses').",
    ),
) -> None:
    """File a derived artifact back into the domain knowledge base.

    Copies the file to <domain-dir>/derived/<category>/<filename> and
    appends a log entry. If a file with the same name already exists,
    a timestamp suffix is added to avoid overwriting.

    This is the Karpathy 'LLM Wiki' pattern: human-curated artifacts
    (expert reviews, annotated comparisons, corrected definitions)
    accumulate in the knowledge base alongside automated extractions.
    """
    from .core.fileback import file_back

    if not source_file.exists():
        console.print(f"[red]File not found:[/] {source_file}")
        raise typer.Exit(code=1)

    dest = file_back(source_file, domain_dir, category=category)
    console.print(
        f"[bold green]Filed back:[/] {dest.relative_to(domain_dir)}"
    )
    console.print(f"[dim]Log entry appended to {domain_dir / 'log.md'}[/]")


# ─── Helper: reconstruct DomainDocumentExtractionResult from JSON ───────────


def _load_source_a_json(path: Path):
    """Reconstruct a single Source A extraction result from JSON.

    The shape matches what ``extract-a --json`` emits. Profile-mode
    concepts carry ``id`` and ``entity_type`` — preserved here so the
    fusion engine can use them for cross-source consolidation.
    Multi-doc fusion calls this once per ``--source-a`` flag.
    """
    import json
    from .extractors.domain_doc_extractor import (
        Concept,
        DomainDocumentExtractionResult,
        FieldConfidence,
        Provenance,
        Relationship,
    )

    raw = json.loads(path.read_text(encoding="utf-8"))

    concepts = []
    for rc in raw.get("concepts", []):
        c = Concept(
            name=rc.get("name", ""),
            definition=rc.get("definition", ""),
            citation=rc.get("citation", ""),
            id=rc.get("id", ""),
            entity_type=rc.get("entity_type", ""),
        )
        for fc in rc.get("confidence", []):
            c.confidence.append(FieldConfidence(
                fc.get("field_name", ""),
                fc.get("score", 0.0),
                fc.get("reason", ""),
            ))
        prov = rc.get("provenance")
        if prov:
            c.provenance = Provenance(
                source_document=prov.get("source_document", ""),
                source_section=prov.get("source_section", ""),
                source_text_snippet=prov.get("source_text_snippet", ""),
                extraction_timestamp=prov.get("extraction_timestamp", ""),
            )
        concepts.append(c)

    relationships = []
    for rr in raw.get("relationships", []):
        r = Relationship(
            subject=rr.get("subject", ""),
            predicate=rr.get("predicate", ""),
            object=rr.get("object", ""),
        )
        for fc in rr.get("confidence", []):
            r.confidence.append(FieldConfidence(
                fc.get("field_name", ""),
                fc.get("score", 0.0),
                fc.get("reason", ""),
            ))
        relationships.append(r)

    res = DomainDocumentExtractionResult(
        domain_name=raw.get("domain_name", ""),
        concepts=concepts,
        relationships=relationships,
        source_documents=raw.get("source_documents", []),
        extraction_timestamp=raw.get("extraction_timestamp", ""),
    )
    console.print(
        f"[bold blue]Source A:[/] {len(concepts)} concepts, "
        f"{len(relationships)} relationships from {path.name}"
    )
    return res


# ─── Helper: reconstruct FusionResult from JSON ─────────────────────────────


def _reconstruct_fusion_result(raw: dict) -> "FusionResult":
    """Reconstruct a FusionResult from the fused JSON output.

    Used by both the lint and query CLI commands. Centralised here to
    avoid duplicating the reconstruction logic.
    """
    from .core.fusion import (
        BusinessRule,
        FieldAnchor,
        FusedElement,
        FusedRelationship,
        FieldConflict,
        FieldProvenance,
        FusionResult,
    )

    def _anchor_from_dict(a: dict | None) -> FieldAnchor | None:
        """Phase 6: read a serialised FieldAnchor back, accepting all
        keys missing (treat as default 0 / empty). Pre-Phase-6 JSON
        files that have no ``anchor`` key on conflict provenances pass
        ``None`` here and the FieldProvenance.anchor stays None —
        round-trip byte-identical."""
        if not a:
            return None
        return FieldAnchor(
            page=a.get("page", 0),
            char_offset=a.get("char_offset", 0),
            char_length=a.get("char_length", 0),
            line=a.get("line", 0),
            end_line=a.get("end_line", 0),
            column=a.get("column", 0),
            segment_id=a.get("segment_id", ""),
            snippet=a.get("snippet", ""),
        )

    def _business_rule_from(item) -> BusinessRule:
        """Tycho 1.0+: read back a BusinessRule from a JSON dict.
        Pre-1.0 fused JSONs stored business_rules as list[str]; for
        backward compat, accept a string and wrap it in a minimal
        BusinessRule with type/name unknown — the description is the
        only payload available."""
        if isinstance(item, str):
            return BusinessRule(
                rule_type="",
                name="",
                expression="",
                description=item,
            )
        return BusinessRule(
            rule_type=item.get("rule_type", ""),
            name=item.get("name", ""),
            expression=item.get("expression", ""),
            description=item.get("description", ""),
            value=item.get("value"),
            referenced_symbols=list(item.get("referenced_symbols", [])),
            citations=list(item.get("citations", [])),
            docstring=item.get("docstring", ""),
            confidence=item.get("confidence", 0.95),
            anchor=_anchor_from_dict(item.get("anchor")),
        )

    # PR2 (property extraction): defensively deserialise the new
    # ``attributes`` key on each element. Legacy fused.json files
    # (written before PR2 landed) have no key — default to ``[]`` so
    # reload remains backwards-compatible.
    from .core.attribute import Attribute

    elements = []
    for re_ in raw.get("elements", []):
        el = FusedElement(
            element_name=re_.get("element_name", ""),
            domain_name=re_.get("domain_name", ""),
            definition=re_.get("definition", ""),
            is_critical=re_.get("is_critical", False),
            citation=re_.get("citation", ""),
            data_type=re_.get("data_type", ""),
            enum_values=re_.get("enum_values", []),
            business_rules=[
                _business_rule_from(item)
                for item in re_.get("business_rules", [])
            ],
            extra_fields=re_.get("extra_fields", {}),
            sources=re_.get("sources", []),
            governance_validated=re_.get("governance_validated", False),
            confidence=re_.get("confidence", 0.0),
            attributes=[
                Attribute.from_json_dict(a) for a in re_.get("attributes", []) or []
            ],
        )
        for rc in re_.get("conflicts", []):
            w = rc.get("winner", {})
            el.conflicts.append(FieldConflict(
                field_name=rc.get("field", ""),
                winner=FieldProvenance(
                    source=w.get("source", ""),
                    confidence=0.0,
                    original_value=w.get("value", ""),
                    anchor=_anchor_from_dict(w.get("anchor")),
                ),
                rejected=[
                    FieldProvenance(
                        source=rj.get("source", ""),
                        confidence=0.0,
                        original_value=rj.get("value", ""),
                        anchor=_anchor_from_dict(rj.get("anchor")),
                    )
                    for rj in rc.get("rejected", [])
                ],
                resolution=rc.get("resolution", ""),
            ))
        elements.append(el)

    relationships = []
    for rr in raw.get("relationships", []):
        relationships.append(FusedRelationship(
            subject=rr.get("subject", ""),
            predicate=rr.get("predicate", ""),
            object=rr.get("object", ""),
            source=rr.get("source", ""),
            confidence=rr.get("confidence", 0.0),
        ))

    return FusionResult(
        elements=elements,
        relationships=relationships,
        sources_used=raw.get("sources_used", []),
        fusion_timestamp=raw.get("fusion_timestamp", ""),
    )


# ─── validate (Phase 4: profile-driven validation, runs before lint) ─────────


@app.command()
def validate(
    fused_json: Path = typer.Argument(
        ...,
        help="Path to a fused dictionary JSON (output of the fuse command).",
    ),
    profile: Path = typer.Option(
        ..., "--profile",
        help=(
            "Path to a profile directory containing schema.json. "
            "Validation rules are profile-defined; this flag is required."
        ),
    ),
    output: Path = typer.Option(
        None, "--output", "-o",
        help=(
            "Optional output path for the validated JSON. If omitted, "
            "the report is printed but no file is written."
        ),
    ),
    mode: str = typer.Option(
        "flag", "--mode",
        help=(
            "'flag' (default): annotate findings, keep all data. "
            "'filter': drop entities that fail VR001/VR002 errors and "
            "cascade-drop their relationships; drop relationships that "
            "fail VR004."
        ),
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help="Per-domain knowledge base directory for audit log.",
    ),
) -> None:
    """Stage 2 power-user command. Most users call `ontozense draft` instead, which runs this and the rest of the pipeline.

    Validate a fused dictionary against a profile schema.

    Runs 6 structural rules (entity uniqueness, type membership,
    required fields, predicate vocabulary, predicate domains,
    cardinality) borrowed from OntoMetric. Findings are reported with
    rule IDs (VR001-VR006) and severities (error / warning).

    With --mode filter, errors cascade-drop the offending entity and
    any relationships referencing it; the validated output is the
    cleaned subset. With --mode flag (default), nothing is dropped —
    findings are annotated for downstream review.

    Exit code 0 if no errors. Exit code 3 if errors found (mirrors
    lint's --max-low semantics so scripts can pipeline check).
    """
    import json
    from .core.profile import load_profile, ProfileError
    from .core.validation import validate as run_validate, VALID_MODES
    from .log import append_log

    if mode not in VALID_MODES:
        console.print(
            f"[bold red][x] Invalid --mode value:[/] {mode!r}. "
            f"Must be one of {sorted(VALID_MODES)}."
        )
        raise typer.Exit(code=1)

    if not fused_json.exists():
        console.print(f"[red]File not found:[/] {fused_json}")
        raise typer.Exit(code=1)

    # Load profile
    try:
        loaded_profile = load_profile(profile)
    except ProfileError as e:
        console.print(f"[bold red][x] Profile load failed:[/] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(
            f"[bold red][x] Profile load failed (filesystem error):[/] "
            f"{type(e).__name__}: {e}"
        )
        raise typer.Exit(code=1)

    raw = json.loads(fused_json.read_text(encoding="utf-8"))
    fusion_result = _reconstruct_fusion_result(raw)

    console.print()
    console.print(
        f"[bold magenta]Validating[/] {fused_json.name} against profile "
        f"[cyan]{loaded_profile.profile_name}[/] "
        f"(version {loaded_profile.profile_version}), mode={mode}"
    )

    result = run_validate(fusion_result, loaded_profile, mode=mode)

    # Display findings grouped by rule
    console.print()
    console.print(
        f"[bold]Validation report:[/] "
        f"{len(fusion_result.elements)} elements -> "
        f"{len(result.elements)} after validation; "
        f"{len(fusion_result.relationships)} relationships -> "
        f"{len(result.relationships)} after validation"
    )

    if not result.findings:
        console.print("[bold green]No findings — output is profile-valid.[/]")
    else:
        rule_labels = {
            "VR001": ("Entity uniqueness", "red"),
            "VR002": ("Type membership", "red"),
            "VR003": ("Required fields", "yellow"),
            "VR004": ("Predicate vocabulary", "red"),
            "VR005": ("Predicate domains", "yellow"),
            "VR006": ("Cardinality", "yellow"),
        }
        for rule_id in ["VR001", "VR002", "VR003", "VR004", "VR005", "VR006"]:
            findings = result.by_rule(rule_id)
            if not findings:
                continue
            label, color = rule_labels[rule_id]
            console.print(
                f"\n[bold {color}]{rule_id} {label} ({len(findings)}):[/]"
            )
            for f in findings[:10]:  # cap displayed per-rule for readability
                icon = {"error": "x", "warning": "!", "info": "-"}[f.severity]
                console.print(f"  [{f.severity}] {icon} {f.message}")
            if len(findings) > 10:
                console.print(
                    f"  [dim]... {len(findings) - 10} more — see "
                    f"output JSON for full list[/]"
                )

    console.print()
    console.print(
        f"[bold]Summary:[/] "
        f"{result.error_count} errors, {result.warning_count} warnings"
    )
    if mode == "filter":
        console.print(
            f"  Cascade filtered: "
            f"{result.cascade_filtered_entities} entities, "
            f"{result.cascade_filtered_relationships} relationships"
        )

    # Write validated output if requested
    if output:
        # Reuse the fused JSON's structure, replacing elements +
        # relationships with the validated set, and adding a
        # validation_summary block.
        out_data = dict(raw)  # shallow copy of top-level keys
        out_data["elements"] = [_serialize_element(el) for el in result.elements]
        out_data["relationships"] = [
            _serialize_relationship(rel) for rel in result.relationships
        ]
        out_data["validation_summary"] = {
            "profile_name": result.profile_name,
            "profile_version": result.profile_version,
            "mode": result.mode,
            "timestamp": result.timestamp,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "by_rule": result.summary,
            "cascade_filtered_entities": result.cascade_filtered_entities,
            "cascade_filtered_relationships": result.cascade_filtered_relationships,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "target_kind": f.target_kind,
                    "target_id": f.target_id,
                    "message": f.message,
                    "details": f.details,
                }
                for f in result.findings
            ],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(out_data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[bold green]Validated dictionary saved:[/] {output}")

    if domain_dir:
        append_log(
            domain_dir, "validate",
            source=fused_json.name,
            profile=loaded_profile.profile_name,
            mode=mode,
            errors=result.error_count,
            warnings=result.warning_count,
            cascade_entities=result.cascade_filtered_entities,
            cascade_relationships=result.cascade_filtered_relationships,
        )

    if result.error_count > 0:
        raise typer.Exit(code=3)


def _serialize_field_provenance(fp) -> dict:
    """Serialize a FieldProvenance entry as it appears under conflict
    winner / rejected nodes.

    Phase 6: emits the ``anchor`` key ONLY when the provenance has a
    non-None, non-empty FieldAnchor. Pre-Phase-6 callers never set
    anchors, so their JSON output is byte-identical to the pre-Phase-6
    shape — that's the AC1 contract.
    """
    out = {"source": fp.source, "value": fp.original_value}
    anchor = getattr(fp, "anchor", None)
    if anchor is not None and not anchor.is_empty():
        out["anchor"] = {
            "page": anchor.page,
            "char_offset": anchor.char_offset,
            "char_length": anchor.char_length,
            "line": anchor.line,
            "end_line": anchor.end_line,
            "column": anchor.column,
            "segment_id": anchor.segment_id,
            "snippet": anchor.snippet,
        }
    return out


def _serialize_business_rule(br) -> dict:
    """Serialize a BusinessRule to a JSON-friendly dict.

    Tycho 1.0+: business_rules went from list[str] to list[BusinessRule].
    Each rule emits all its typed fields. ``anchor`` is omitted when
    None or empty, mirroring the FieldAnchor serialisation policy.
    For backward compat with code that sneaks raw strings into
    business_rules, fall back to wrapping the string in a minimal
    dict with only ``description`` set.
    """
    if isinstance(br, str):
        return {"rule_type": "", "name": "", "expression": "",
                "description": br}
    out = {
        "rule_type": br.rule_type,
        "name": br.name,
        "expression": br.expression,
        "description": br.description,
        "value": br.value,
        "referenced_symbols": list(br.referenced_symbols),
        "citations": list(br.citations),
        "docstring": br.docstring,
        "confidence": br.confidence,
    }
    anchor = getattr(br, "anchor", None)
    if anchor is not None and not anchor.is_empty():
        out["anchor"] = {
            "page": anchor.page,
            "char_offset": anchor.char_offset,
            "char_length": anchor.char_length,
            "line": anchor.line,
            "end_line": anchor.end_line,
            "column": anchor.column,
            "segment_id": anchor.segment_id,
            "snippet": anchor.snippet,
        }
    return out


def _serialize_element(el) -> dict:
    """Serialize a FusedElement to a JSON-friendly dict.

    Mirrors the shape produced by the fuse command so validate's output
    is compatible with downstream lint / consumers.

    PR2 (property extraction): adds ``attributes`` to the whitelist so
    the typed properties land in fused.json. Empty list when nothing
    matched the element — preserves backwards-compat for fixtures
    without attributes.
    """
    return {
        "element_name": el.element_name,
        "domain_name": el.domain_name,
        "definition": el.definition,
        "is_critical": el.is_critical,
        "citation": el.citation,
        "data_type": el.data_type,
        "enum_values": el.enum_values,
        "business_rules": [
            _serialize_business_rule(br) for br in el.business_rules
        ],
        "governance_validated": el.governance_validated,
        "confidence": round(el.confidence, 3),
        "sources": el.sources,
        "needs_review": el.needs_review(),
        "conflicts": [
            {
                "field": c.field_name,
                "winner": _serialize_field_provenance(c.winner),
                "rejected": [
                    _serialize_field_provenance(r) for r in c.rejected
                ],
                "resolution": c.resolution,
            }
            for c in el.conflicts
        ],
        "extra_fields": el.extra_fields,
        "attributes": [
            a.to_json_dict() for a in getattr(el, "attributes", []) or []
        ],
    }


def _serialize_relationship(rel) -> dict:
    """Serialize a FusedRelationship to a JSON-friendly dict."""
    return {
        "subject": rel.subject,
        "predicate": rel.predicate,
        "object": rel.object,
        "source": rel.source,
        "confidence": round(rel.confidence, 3),
    }


# ─── lint (Step 7: consistency check on fused output) ────────────────────────


@app.command()
def lint(
    fused_json: Path = typer.Argument(
        ...,
        help="Path to a fused dictionary JSON (output of the fuse command).",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help="Per-domain knowledge base directory for audit log.",
    ),
    max_gaps: int = typer.Option(
        10, "--max-gaps",
        help="Maximum number of structural gap warnings to report. "
             "Extra gaps are summarised (default: 10).",
    ),
    max_bridges: int = typer.Option(
        10, "--max-bridges",
        help="Maximum number of bridge concept findings to report. "
             "Extra bridges are summarised (default: 10).",
    ),
) -> None:
    """Stage 2 power-user command. Most users call `ontozense draft` instead, which runs this and the rest of the pipeline.

    Run consistency checks on a fused data dictionary.

    Checks for contradictions between sources, orphan terms not
    referenced by any relationship, undefined relationship endpoints,
    coverage gaps (missing definitions or citations), and structural
    gaps (disconnected concept clusters via graph analysis).
    """
    import json
    from .core.lint import lint as run_lint
    from .log import append_log

    if not fused_json.exists():
        console.print(f"[red]File not found:[/] {fused_json}")
        raise typer.Exit(code=1)

    raw = json.loads(fused_json.read_text(encoding="utf-8"))
    fusion_result = _reconstruct_fusion_result(raw)

    # Run lint
    report = run_lint(fusion_result, max_gaps=max_gaps, max_bridges=max_bridges)

    # Display results
    console.print()
    console.print(f"[bold]Lint report for[/] {fused_json.name}")
    console.print(
        f"  Elements: {len(fusion_result.elements)}   "
        f"Relationships: {len(fusion_result.relationships)}   "
        f"Sources: {'+'.join(fusion_result.sources_used)}"
    )
    console.print()

    if not report.findings:
        console.print("[bold green]No issues found.[/]")
    else:
        # Group by category
        for category in ["contradiction", "undefined_used", "orphan", "coverage_gap", "structural_gap"]:
            findings = report.by_category(category)
            if not findings:
                continue
            label = {
                "contradiction": "Contradictions",
                "undefined_used": "Undefined but used",
                "orphan": "Orphan terms",
                "coverage_gap": "Coverage gaps",
                "structural_gap": "Structural gaps",
            }[category]
            color = {
                "contradiction": "red",
                "undefined_used": "yellow",
                "orphan": "cyan",
                "coverage_gap": "yellow",
                "structural_gap": "magenta",
            }[category]
            console.print(f"[bold {color}]{label} ({len(findings)}):[/]")
            for f in findings:
                icon = {"error": "x", "warning": "!", "info": "-"}[f.severity]
                console.print(f"  [{f.severity}] {icon} {f.message}")
            console.print()

    summary = report.summary
    console.print(
        f"[bold]Summary:[/] "
        f"{report.error_count} errors, "
        f"{report.warning_count} warnings, "
        f"{len(report.findings) - report.error_count - report.warning_count} info"
    )

    if domain_dir:
        append_log(
            domain_dir, "lint",
            source=fused_json.name,
            **{k: v for k, v in summary.items()},
            errors=report.error_count,
            warnings=report.warning_count,
        )

    # Exit code reflects lint severity
    if report.error_count > 0:
        raise typer.Exit(code=1)


# ─── report (Phase 7: benchmark metrics on a fused output) ──────────────────


@app.command()
def report(
    fused_json: Path = typer.Argument(
        ...,
        help="Path to a fused dictionary JSON (output of the fuse command).",
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional profile directory. When supplied, the report "
            "includes a profile-coverage section showing which "
            "declared entity_types and predicates were populated."
        ),
    ),
    reference: Path = typer.Option(
        None, "--reference",
        help=(
            "Optional reference data dictionary (a fused-shape JSON "
            "file representing the curated truth). When supplied, "
            "the report includes precision / recall / F1 of the "
            "fused output against the reference, both for elements "
            "and for relationships."
        ),
    ),
    output: Path = typer.Option(
        None, "--output", "-o",
        help=(
            "Path to write the JSON benchmark snapshot. Machine-"
            "diffable for run-vs-run comparison."
        ),
    ),
    markdown: Path = typer.Option(
        None, "--markdown", "-m",
        help=(
            "Path to write the markdown rendering. If omitted, the "
            "markdown is printed to stdout."
        ),
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help=(
            "Per-domain knowledge base directory for audit log and "
            "auto file-back of the markdown report."
        ),
    ),
) -> None:
    """Compute a benchmark snapshot from a fused output (Phase 7).

    Reports element counts (by source combination, governance-validated,
    multi-source), confidence distribution, conflict statistics, anchor
    coverage (Phase 6), multi-doc corroboration (Phase 5), and — when a
    profile is supplied — declared-vs-used coverage of entity_types
    and predicates.

    Always writes a JSON snapshot when --output is given (machine-
    diffable). Always renders markdown — to --markdown if supplied,
    otherwise to stdout.
    """
    import json
    from .core.benchmark import compute_benchmark, render_markdown
    from .log import append_log

    if not fused_json.exists():
        console.print(f"[red]File not found:[/] {fused_json}")
        raise typer.Exit(code=1)

    raw = json.loads(fused_json.read_text(encoding="utf-8"))
    fusion_result = _reconstruct_fusion_result(raw)

    loaded_profile = None
    if profile is not None:
        from .core.profile import load_profile, ProfileError
        try:
            loaded_profile = load_profile(profile)
        except ProfileError as e:
            console.print(f"[bold red][x] Profile load failed:[/] {e}")
            raise typer.Exit(code=1)
        except OSError as e:
            console.print(
                f"[bold red][x] Profile load failed (filesystem error):[/] "
                f"{type(e).__name__}: {e}"
            )
            raise typer.Exit(code=1)

    # Tycho 1.0+ wrap-up #3: optional --reference compares the fused
    # output against a curated truth dictionary and emits P/R/F1.
    loaded_reference = None
    reference_path_str = ""
    if reference is not None:
        from .core.benchmark import (
            ReferenceContractError, validate_reference_shape,
        )
        if not reference.exists():
            console.print(
                f"[bold red][x] Reference file not found:[/] {reference}"
            )
            raise typer.Exit(code=1)
        try:
            ref_raw = json.loads(reference.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            console.print(
                f"[bold red][x] Reference JSON parse error:[/] {reference}"
            )
            console.print(f"  [dim]Line {e.lineno}, col {e.colno}: {e.msg}[/]")
            console.print(
                "  The reference file should be a fused-shape JSON: "
                "an object with [cyan]elements[/] and (optionally) "
                "[cyan]relationships[/] arrays."
            )
            raise typer.Exit(code=1)
        # Round-4 review fix: structural validation BEFORE
        # reconstruction so a malformed-but-syntactically-valid
        # reference produces a clean message instead of an
        # AttributeError traceback during _reconstruct_fusion_result.
        try:
            validate_reference_shape(ref_raw)
        except ReferenceContractError as e:
            console.print(
                f"[bold red][x] Reference JSON contract error:[/] "
                f"{reference}"
            )
            console.print(f"  [dim]{e}[/]")
            raise typer.Exit(code=1)
        loaded_reference = _reconstruct_fusion_result(ref_raw)
        reference_path_str = str(reference)

    report_obj = compute_benchmark(
        fusion_result,
        profile=loaded_profile,
        reference=loaded_reference,
        reference_path=reference_path_str,
    )
    md = render_markdown(report_obj)

    # Always emit markdown — to file if requested, else to stdout
    if markdown:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(md, encoding="utf-8")
        console.print(f"[bold green]Markdown report saved:[/] {markdown}")
    else:
        console.print(md)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report_obj.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[bold green]JSON snapshot saved:[/] {output}")

    if domain_dir:
        # Auto file-back the markdown report when both --markdown and
        # --domain-dir are given (matches existing query / lint UX).
        if markdown:
            from .core.fileback import file_back
            dest = file_back(markdown, domain_dir, category="reports")
            console.print(
                f"[bold green]Filed back:[/] "
                f"{dest.relative_to(domain_dir)}"
            )
        append_log(
            domain_dir, "report",
            source=fused_json.name,
            elements=report_obj.elements.total,
            governance_validated=report_obj.elements.governance_validated,
            conflicts=report_obj.conflicts.total_conflicts,
            anchored_provenance_entries=report_obj.anchors.with_anchor,
        )


# ─── fuse (Step 6: combine sources into rich data dictionary) ────────────────


@app.command()
def fuse(
    source_a_json: list[Path] = typer.Option(
        None, "--source-a", "-a",
        help=(
            "Source A extraction result (JSON from extract-a --json). "
            "Repeat the flag to fuse multiple authoritative documents — "
            "concepts that share an id (profile mode) or normalised name "
            "(unconstrained) are consolidated; each contributing document "
            "is recorded in extra_fields.source_documents."
        ),
    ),
    source_b_json: Path = typer.Option(
        None, "--source-b", "-b",
        help="Source B governance reference file (JSON).",
    ),
    source_c_dir: Path = typer.Option(
        None, "--source-c", "-c",
        help=(
            "Source C schema: path to a SchemaResult JSON file. "
            "Produce it with an adapter — see adapters/django/ or "
            "adapters/postgres/ for examples, or write your own "
            "targeting ontozense.core.source_c."
        ),
    ),
    source_d_dir: Path = typer.Option(
        None, "--source-d", "-d",
        help="Source D code: path to a directory of Python/SQL files.",
    ),
    output: Path = typer.Option(
        "fused-dictionary.json",
        "--output", "-o",
        help="Output JSON file for the fused rich data dictionary.",
    ),
    domain_dir: Path = typer.Option(
        None, "--domain-dir",
        help="Per-domain knowledge base directory for audit log.",
    ),
    priority: str = typer.Option(
        "A,B,C,D", "--priority",
        help="Conflict resolution priority order (comma-separated).",
    ),
) -> None:
    """Stage 2 power-user command. Most users call `ontozense draft` instead, which orchestrates fuse + validate + lint + OWL emission.

    Fuse Sources A, B, C, D into a rich data dictionary.

    Takes extraction results from individual sources and combines them
    into a single fused output with per-field provenance, governance
    validation status, conflict detection, and confidence scoring.

    At least one source must be provided. All sources are optional —
    the minimum viable fusion is Source A alone.
    """
    import json
    from dataclasses import asdict
    from .core.fusion import FusionEngine
    from .log import append_log

    # ── Load sources ──
    sa: list = []
    sb = sc = sd = None

    if source_a_json:
        for src_path in source_a_json:
            try:
                sa.append(_load_source_a_json(src_path))
            except OSError as e:
                console.print(
                    f"[bold red][x] Source A file error:[/] {src_path}"
                )
                console.print(f"  [dim]{type(e).__name__}: {e}[/]")
                console.print(
                    "  Check that the path exists and is readable."
                )
                raise typer.Exit(code=1)
            except json.JSONDecodeError as e:
                console.print(
                    f"[bold red][x] Source A JSON parse error:[/] "
                    f"{src_path}"
                )
                console.print(
                    f"  [dim]Line {e.lineno}, col {e.colno}: {e.msg}[/]"
                )
                console.print(
                    "  The file should be the output of "
                    "[cyan]extract-a --json[/]."
                )
                raise typer.Exit(code=1)
            # Per-doc summary line — concepts/relationships logged in helper.

    if source_b_json:
        from .extractors.governance_extractor import GovernanceExtractor
        sb = GovernanceExtractor().extract_from_file(source_b_json)
        console.print(
            f"[bold blue]Source B:[/] {len(sb.records)} governance records "
            f"from {source_b_json.name}"
        )

    if source_c_dir:
        # Tycho 1.0+: Source C is a JSON file conforming to the
        # SchemaResult contract in ontozense.core.source_c. Adapters
        # that produce this JSON live outside the package (see
        # adapters/django/, adapters/postgres/, or write your own).
        from .core.source_c import load_source_c_json, SourceCContractError
        # If the user passes a directory (the pre-1.0 input shape)
        # surface a migration hint inline so they don't have to dig
        # through the README.
        if source_c_dir.is_dir():
            console.print(
                f"[bold red][x] Source C is now a JSON file, "
                f"not a directory:[/] {source_c_dir}"
            )
            console.print(
                "  In Tycho 1.0 the CLI consumes a SchemaResult JSON "
                "produced by an adapter. For a Django models directory:"
            )
            console.print(
                f"    [cyan]python -m adapters.django.django_to_json "
                f"{source_c_dir} --output source-c.json[/]"
            )
            console.print(
                "  Then re-run with [cyan]--source-c source-c.json[/]."
            )
            console.print(
                "  See adapters/README.md for other adapters / writing "
                "your own."
            )
            raise typer.Exit(code=1)
        try:
            sc = load_source_c_json(source_c_dir)
        except OSError as e:
            console.print(
                f"[bold red][x] Source C file error:[/] {source_c_dir}"
            )
            console.print(f"  [dim]{type(e).__name__}: {e}[/]")
            console.print(
                "  Source C is a JSON file. See adapters/django/README.md "
                "for an example of producing one from Django models."
            )
            raise typer.Exit(code=1)
        except json.JSONDecodeError as e:
            console.print(
                f"[bold red][x] Source C JSON parse error:[/] "
                f"{source_c_dir}"
            )
            console.print(
                f"  [dim]Line {e.lineno}, col {e.colno}: {e.msg}[/]"
            )
            console.print(
                "  The file should be a SchemaResult JSON — see "
                "[cyan]ontozense.core.source_c[/]."
            )
            raise typer.Exit(code=1)
        except SourceCContractError as e:
            console.print(
                f"[bold red][x] Source C JSON contract error:[/] "
                f"{source_c_dir}"
            )
            console.print(f"  [dim]{e}[/]")
            console.print(
                "  See adapters/README.md for the SchemaResult contract."
            )
            raise typer.Exit(code=1)
        console.print(
            f"[bold blue]Source C:[/] {len(sc.models)} schema models "
            f"from {source_c_dir.name}"
        )

    if source_d_dir:
        from .extractors.code_extractor import CodeExtractor
        sd = CodeExtractor().extract_from_directory(source_d_dir)
        console.print(
            f"[bold blue]Source D:[/] {len(sd.rules)} code rules "
            f"from {source_d_dir}"
        )

    if not any([sa, sb, sc, sd]):
        console.print("[red]No sources provided. Use --source-a, --source-b, "
                      "--source-c, and/or --source-d.[/]")
        raise typer.Exit(code=1)

    # ── Fuse ──
    priority_list = [p.strip().upper() for p in priority.split(",")]
    engine = FusionEngine(priority_order=priority_list)
    result = engine.fuse(source_a=sa, source_b=sb, source_c=sc, source_d=sd)

    # ── Summary ──
    console.print()
    console.print(f"[bold green]Fused {len(result.elements)} elements[/] "
                  f"from sources {'+'.join(result.sources_used)}")
    console.print(
        f"  Governance-validated: [cyan]{result.governance_validated_count}[/]   "
        f"Conflicts: [yellow]{result.conflict_count}[/]   "
        f"Relationships: [cyan]{len(result.relationships)}[/]"
    )
    if result.unmatched_governance:
        console.print(
            f"  [yellow]Governance-only (not in Source A): "
            f"{len(result.unmatched_governance)}[/]"
        )
    if result.unmatched_schema_fields:
        console.print(
            f"  [yellow]Schema-only fields: "
            f"{len(result.unmatched_schema_fields)}[/]"
        )
    if result.unmatched_code_rules:
        console.print(
            f"  [yellow]Unmatched code rules: "
            f"{len(result.unmatched_code_rules)}[/]"
        )

    # ── Write output ──
    # PR2 r1 (Codex blocker 1): use the shared _serialize_element helper
    # so standalone `fuse` produces the same element shape as
    # `_run_fuse_for_draft` / validate / lint paths. Pre-PR2 r1 this
    # block built the dict by hand and silently omitted ``attributes``,
    # making fuse-produced fused.json structurally diverge from
    # draft-produced fused.json (per PR2 r0 review).
    out_data = {
        "fusion_timestamp": result.fusion_timestamp,
        "sources_used": result.sources_used,
        "summary": {
            "total_elements": len(result.elements),
            "governance_validated": result.governance_validated_count,
            "conflicts": result.conflict_count,
            "relationships": len(result.relationships),
            "unmatched_governance": len(result.unmatched_governance),
            "unmatched_schema_fields": len(result.unmatched_schema_fields),
            "unmatched_code_rules": len(result.unmatched_code_rules),
        },
        "elements": [_serialize_element(el) for el in result.elements],
        "relationships": [
            {
                "subject": r.subject,
                "predicate": r.predicate,
                "object": r.object,
                "source": r.source,
                "confidence": round(r.confidence, 3),
            }
            for r in result.relationships
        ],
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(out_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[bold green]Fused dictionary saved:[/] {output}")

    # ── Log ──
    if domain_dir:
        append_log(
            domain_dir, "fuse",
            sources="+".join(result.sources_used),
            elements=len(result.elements),
            governance_validated=result.governance_validated_count,
            conflicts=result.conflict_count,
            relationships=len(result.relationships),
            output=str(output),
        )


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
                console.print(f"  {old} -> {new}")

    if deduplicate:
        dupes = mgr.find_duplicates()
        if dupes:
            console.print("[yellow]Potential duplicates found:[/]")
            for a, b, score in dupes:
                console.print(f"  {a} <-> {b} (similarity: {score:.0%})")
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


# ─── discover (profile induction workflow) ──────────────────────────────────


@app.command(name="discover")
def discover(
    source_a: list[Path] = typer.Option(
        None, "--source-a",
        help=(
            "Path to a Source A extraction JSON. Repeatable — every "
            "occurrence's concepts and relationships lists are concatenated "
            "before building the candidate graph."
        ),
    ),
    source_b: list[Path] = typer.Option(
        None, "--source-b",
        help=(
            "Path to a Source B governance JSON. Repeatable. Accepts the "
            "same shapes the governance extractor does: a single object "
            "({'element_name': ...}), a top-level array of such objects "
            "(the shape of docs/governance_example.json), or a "
            "{'records': [...]} wrapper."
        ),
    ),
    source_c: list[Path] = typer.Option(
        None, "--source-c",
        help=(
            "Path to a Source C schema JSON. Repeatable. The flag is "
            "accepted and the payload is passed through unchanged; "
            "Source C contents do not affect candidate generation in "
            "this implementation."
        ),
    ),
    source_d: list[Path] = typer.Option(
        None, "--source-d",
        help=(
            "Path to a Source D code / rules JSON. Repeatable. The "
            "flag is accepted and the payload is passed through "
            "unchanged; Source D contents do not affect candidate "
            "generation in this implementation."
        ),
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional profile directory. Only its alias_map is consulted "
            "(light label normalisation across sources). The profile's "
            "type vocabulary, predicates, and validation rules are NOT "
            "applied — discovery surfaces every candidate the extractors "
            "found."
        ),
    ),
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help=(
            "Output directory. Discovery artifacts are written under "
            "<domain_dir>/discovery/."
        ),
    ),
) -> None:
    """Stage 1 power-user command. Most users call `ontozense survey` instead, which orchestrates extract-a + this in one go.

    Build a candidate graph from raw source extractions.

    Writes three artifacts under ``<DOMAIN_DIR>/discovery/``:

      - ``candidate-graph.json`` — concepts + relationships.
      - ``candidate-provenance.json`` — per-candidate evidence
        breakdown, so a reviewer can trace any candidate back to
        the source row it came from.
      - ``concept-mappings.json`` — written as
        ``{"mappings": []}``. No command in this implementation
        populates it.

    Discovery is intentionally permissive: it does not filter
    candidates by score or type. Run ``induce-profile`` afterwards
    to apply relevance scoring + classification.
    """
    import json

    from .core.candidate_graph import build_candidate_graph
    from .core.profile import ProfileError, load_profile

    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)

    # ── Load and merge source inputs ──
    try:
        merged_a = _merge_source_a(source_a or [])
        merged_b = _merge_source_b(source_b or [])
        merged_c = _load_source_passthrough(source_c or [])
        merged_d = _load_source_passthrough(source_d or [])
    except _SourceLoadError as err:
        console.print(
            f"[red]Failed to load source file {err.path}:[/] {err}"
        )
        raise typer.Exit(code=2)

    # ── Resolve optional --profile to its alias_map (only) ──
    alias_map: dict[str, str] | None = None
    if profile is not None:
        try:
            loaded = load_profile(profile)
        except ProfileError as err:
            console.print(
                f"[red]Failed to load --profile from {profile}:[/] {err}"
            )
            raise typer.Exit(code=2)
        # Defensive copy — the loaded Profile is frozen but its
        # alias_map dict is not, and we don't want a downstream
        # mutation to leak back into a re-used profile instance.
        alias_map = dict(loaded.alias_map)

    # ── Build the candidate graph ──
    graph = build_candidate_graph(
        source_a=merged_a,
        source_b=merged_b,
        source_c=merged_c,
        source_d=merged_d,
        alias_map=alias_map,
    )

    # ── Write the three artifacts ──
    (discovery_dir / "candidate-graph.json").write_text(
        json.dumps(graph.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    provenance = {
        "concepts": [
            {
                "candidate_id": c.candidate_id,
                "label": c.label,
                "provenance": [p.to_dict() for p in c.provenance],
            }
            for c in graph.concepts
        ],
    }
    (discovery_dir / "candidate-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n",
        encoding="utf-8",
    )
    (discovery_dir / "concept-mappings.json").write_text(
        json.dumps({"mappings": []}, indent=2) + "\n",
        encoding="utf-8",
    )

    console.print(
        f"[green]Discovery artifacts written to[/] {discovery_dir}"
    )


# ─── Source-loading helpers (discover) ──────────────────────────────────────


class _SourceLoadError(Exception):
    """Raised when a discovery source file can't be loaded. Carries
    the path so the CLI can surface a clean error message without
    showing a traceback to the user."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


def _load_json(path: Path) -> dict:
    """Load a single JSON source file, wrapping the typical I/O and
    decode failure modes as :class:`_SourceLoadError` so the
    discover command can surface a clean error.
    """
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise _SourceLoadError(path, f"file not found: {path}") from err
    except json.JSONDecodeError as err:
        raise _SourceLoadError(path, f"invalid JSON: {err}") from err
    except OSError as err:
        raise _SourceLoadError(path, f"could not read: {err}") from err


def _merge_source_a(paths: list[Path]) -> dict | None:
    """Concatenate ``concepts`` and ``relationships`` across one or
    more Source A JSON files. Returns ``None`` when no paths are
    given so :func:`build_candidate_graph` treats that as "no
    Source A contribution" (rather than empty-but-present).

    Each file must be a JSON object — the ``extract-a --json``
    output shape — and its ``concepts`` / ``relationships`` fields
    (if present) must be lists of objects. Malformed payloads at
    any of these levels raise :class:`_SourceLoadError` with a hint
    about the accepted shape, matching the friendly exit-2 path the
    rest of the discover workflow uses for malformed inputs.
    """
    if not paths:
        return None
    merged: dict = {"concepts": [], "relationships": []}
    for path in paths:
        raw = _load_json(path)
        if not isinstance(raw, dict):
            raise _SourceLoadError(
                path,
                f"Source A file must be a JSON object "
                f"(got top-level {type(raw).__name__}). "
                f"Expected the shape produced by "
                f"`ontozense extract-a --json`: "
                f"{{'concepts': [...], 'relationships': [...]}}.",
            )
        _validate_source_a_inner_shape(raw, path)
        merged["concepts"].extend(raw.get("concepts", []))
        merged["relationships"].extend(raw.get("relationships", []))
    return merged


def _validate_source_a_inner_shape(payload: dict, path: Path) -> None:
    """Validate the inner shape of a Source A JSON payload: the
    optional ``concepts`` and ``relationships`` fields, if present,
    must each be a list of objects.

    Without this guard, a payload like ``{"concepts": "oops"}``
    would iterate over each character of the string, or
    ``{"concepts": ["bad"]}`` would call ``.get()`` on a bare
    string — either way leaking ``AttributeError`` instead of the
    friendly exit-2 path. Mirrors the same defensive shape check
    :func:`_normalise_source_b_payload` does for Source B.
    """
    for field, entry_label in (
        ("concepts", "concept"),
        ("relationships", "relationship"),
    ):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list):
            raise _SourceLoadError(
                path,
                f"Source A {field!r} field must be a list "
                f"(got {type(value).__name__}).",
            )
        for idx, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise _SourceLoadError(
                    path,
                    f"Source A {field}[{idx}] is not a JSON object "
                    f"(got {type(entry).__name__}). Every "
                    f"{entry_label} entry must be an object.",
                )


def _merge_source_b(paths: list[Path]) -> dict | None:
    """Concatenate the governance records across one or more Source B
    JSON files, normalising each file's shape on the way in.

    Accepts the three shapes a real Source B file can have:

      - **Single object** (e.g. one-record governance file) —
        ``{"element_name": "...", ...}`` → wrapped as a length-1
        records list.
      - **Top-level array** — the shape of
        ``docs/governance_example.json`` and the array form the
        governance extractor accepts → used directly.
      - **Wrapped form** — ``{"records": [...]}`` — the internal
        shape :func:`build_candidate_graph` consumes natively;
        accepted for round-trip with any pipeline that emits it.

    Anything else raises :class:`_SourceLoadError` so the CLI can
    surface a clean exit-2 message instead of a traceback. Same
    ``None``-vs-empty semantics as :func:`_merge_source_a`.
    """
    if not paths:
        return None
    merged: dict = {"records": []}
    for path in paths:
        raw = _load_json(path)
        merged["records"].extend(_normalise_source_b_payload(raw, path))
    return merged


def _normalise_source_b_payload(payload, path: Path) -> list:
    """Map one raw Source B JSON payload to a list of record dicts.

    See :func:`_merge_source_b` for the accepted input shapes.
    Validates that array entries are objects so a mixed array
    (``[{...}, "stray"]``) fails loudly with the offending index
    rather than crashing inside the candidate-graph builder.
    """
    # Wrapped form: pass the records list through (still validate
    # entries are dicts so a malformed wrapper doesn't crash later).
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        _validate_record_entries(payload["records"], path, context="records")
        return payload["records"]

    # Single governance object: an object with an element_name field.
    if isinstance(payload, dict) and isinstance(
        payload.get("element_name"), str
    ):
        return [payload]

    # Top-level array of governance objects.
    if isinstance(payload, list):
        _validate_record_entries(payload, path, context="array")
        return payload

    # Empty dict is ambiguous but harmless — no records, no error.
    if isinstance(payload, dict) and not payload:
        return []

    # Anything else: the caller gave us a JSON shape we can't map
    # to records. Surface a friendly error explaining what's
    # accepted so they can self-diagnose.
    type_name = type(payload).__name__
    raise _SourceLoadError(
        path,
        f"Source B file shape not recognised (got top-level {type_name}). "
        f"Accepted shapes: a single governance object "
        f"{{'element_name': ...}}, an array of such objects "
        f"(see docs/governance_example.json), or a "
        f"{{'records': [...]}} wrapper.",
    )


def _validate_record_entries(
    entries: list, path: Path, *, context: str,
) -> None:
    """Pin each Source B array / records entry to an object. A non-
    object entry (string, number, null, nested list) is the
    classic AttributeError-on-`.get()` trap; raising here surfaces
    the entry index in the error message so the user can find the
    bad row in their file."""
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _SourceLoadError(
                path,
                f"Source B {context}[{idx}] is not an object "
                f"(got {type(entry).__name__}). Every governance "
                f"record must be a JSON object with at least an "
                f"element_name field.",
            )


def _load_source_passthrough(paths: list[Path]) -> dict | None:
    """Generic loader / merger for the Source C and Source D
    ``--source-*`` flags on ``discover``.

    Single-file inputs pass through unchanged. Multi-file inputs
    are last-write-wins on the top-level dict. The merged dict is
    returned to the caller; :func:`build_candidate_graph` does not
    extract candidate concepts or relationships from these
    payloads in this implementation.
    """
    if not paths:
        return None
    if len(paths) == 1:
        return _load_json(paths[0])
    merged: dict = {}
    for path in paths:
        merged.update(_load_json(path))
    return merged


# ─── induce-profile (profile induction workflow) ────────────────────────────


@app.command(name="induce-profile")
def induce_profile(
    candidate_graph: Path = typer.Argument(
        ...,
        help=(
            "Path to a candidate-graph.json file (typically produced by "
            "``ontozense discover``)."
        ),
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir",
        help="Directory to write the induced profile into. Created if missing.",
    ),
    domain_name: str = typer.Option(
        ..., "--domain-name",
        help="Becomes ``profile_name`` in the emitted schema.json.",
    ),
    weights: Path = typer.Option(
        None, "--weights",
        help=(
            "Optional JSON file with per-signal weights. Must be a flat "
            "object containing every key in DEFAULT_WEIGHTS (7 signals). "
            "Defaults to DEFAULT_WEIGHTS when omitted."
        ),
    ),
    thresholds: Path = typer.Option(
        None, "--thresholds",
        help=(
            "Optional JSON file with classification thresholds. Must be a "
            "flat object with ``core_business`` and "
            "``supporting_technical`` keys. Defaults to "
            "DEFAULT_THRESHOLDS when omitted."
        ),
    ),
) -> None:
    """Stage 2 power-user command. Most users call `ontozense draft` instead, which runs scoring + induction + the rest of the pipeline.

    Score a candidate graph and emit an induced draft profile.

    Reads ``<CANDIDATE_GRAPH>``, applies the relevance scoring stage
    (``core_business`` / ``supporting_technical`` / ``noise``), and
    writes a loader-compatible profile directory under
    ``<OUTPUT_DIR>``:

      - schema.json
      - alias_map.json
      - prompt_fragment.md
      - induction_report.json

    The induction report records the exact weights and thresholds
    used (defaults when no override is given), so a reviewer can
    reproduce the band assignments end-to-end.
    """
    from .core.discovery_contracts import CandidateConcept
    from .core.profile_induction import write_induced_profile
    from .core.relevance import (
        DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, score_candidates,
    )

    # ── Load the candidate graph ──
    try:
        raw = _load_json(candidate_graph)
    except _SourceLoadError as err:
        console.print(
            f"[red]Failed to load candidate graph {err.path}:[/] {err}"
        )
        raise typer.Exit(code=2)

    if not isinstance(raw, dict):
        console.print(
            f"[red]Candidate graph {candidate_graph} is not a JSON "
            f"object[/] (got {type(raw).__name__})"
        )
        raise typer.Exit(code=2)

    concepts_raw = raw.get("concepts", [])
    if not isinstance(concepts_raw, list):
        console.print(
            f"[red]Candidate graph {candidate_graph} has non-list "
            f"'concepts' field[/] (got {type(concepts_raw).__name__})."
        )
        raise typer.Exit(code=2)

    # Reconstruct candidates one at a time so the error message can
    # cite the offending entry's index. The catch covers the four
    # exception types CandidateConcept.from_dict() can surface for
    # malformed input — including ValueError from ``dict(raw)`` on
    # a non-object concept entry (round-1 reviewer finding), which
    # the previous narrower catch missed.
    concepts: list = []
    for i, c in enumerate(concepts_raw):
        try:
            if not isinstance(c, dict):
                raise TypeError(
                    f"expected a JSON object, got {type(c).__name__}"
                )
            concepts.append(CandidateConcept.from_dict(c))
        except (TypeError, KeyError, ValueError, AttributeError) as err:
            console.print(
                f"[red]Candidate graph {candidate_graph} concept entry "
                f"[{i}] is malformed:[/] {err}"
            )
            raise typer.Exit(code=2)

    # ── Optional weights / thresholds overrides ──
    weight_map: dict[str, float] | None = None
    if weights is not None:
        try:
            weight_map = _load_scoring_config(
                weights,
                required_keys=set(DEFAULT_WEIGHTS.keys()),
                label="--weights",
            )
        except _SourceLoadError as err:
            console.print(
                f"[red]Failed to load --weights {err.path}:[/] {err}"
            )
            raise typer.Exit(code=2)

    threshold_map: dict[str, float] | None = None
    if thresholds is not None:
        try:
            threshold_map = _load_scoring_config(
                thresholds,
                required_keys=set(DEFAULT_THRESHOLDS.keys()),
                label="--thresholds",
            )
        except _SourceLoadError as err:
            console.print(
                f"[red]Failed to load --thresholds {err.path}:[/] {err}"
            )
            raise typer.Exit(code=2)

    # ── Score, then write ──
    scored = score_candidates(
        concepts, weights=weight_map, thresholds=threshold_map,
    )
    out_path = write_induced_profile(
        domain_name=domain_name,
        candidates=scored,
        out_dir=output_dir,
        weights=weight_map,
        thresholds=threshold_map,
    )

    # ── Console summary ──
    _print_induction_summary(scored, out_path)


# ─── Scoring-config helpers (induce-profile) ────────────────────────────────


def _load_scoring_config(
    path: Path,
    *,
    required_keys: set[str],
    label: str,
) -> dict[str, float]:
    """Load a JSON scoring-config file (``--weights`` or
    ``--thresholds``) and validate it's a complete, flat,
    numeric-valued dict.

    Strict checks (any failure raises :class:`_SourceLoadError`
    so the CLI surfaces a clean exit-2 message):

      - top level must be a JSON object;
      - every key in ``required_keys`` must be present (lists the
        missing keys in the error so the user can patch the file);
      - extra keys are flagged so typos don't silently get ignored;
      - every value must be a number (``int`` or ``float``).

    The completeness check mirrors :func:`score_candidates`' own
    contract (missing keys → ``KeyError`` downstream). Validating
    at the CLI boundary surfaces a friendly message instead.
    """
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise _SourceLoadError(
            path,
            f"{label} file must be a JSON object "
            f"(got top-level {type(raw).__name__}).",
        )

    present = set(raw.keys())
    missing = required_keys - present
    if missing:
        raise _SourceLoadError(
            path,
            f"{label} file is missing required keys: "
            f"{sorted(missing)}. Expected exactly: "
            f"{sorted(required_keys)}.",
        )
    extra = present - required_keys
    if extra:
        raise _SourceLoadError(
            path,
            f"{label} file has unexpected keys: {sorted(extra)}. "
            f"Expected only: {sorted(required_keys)}.",
        )

    for key, value in raw.items():
        # Reject bools explicitly — ``True`` is a subclass of
        # ``int`` so otherwise it'd slip through and become 1.0,
        # which is almost certainly a config mistake the user
        # wants flagged.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _SourceLoadError(
                path,
                f"{label}[{key!r}] must be a number "
                f"(got {type(value).__name__}: {value!r}).",
            )

    return {k: float(v) for k, v in raw.items()}


def _print_induction_summary(scored, out_path: Path) -> None:
    """Print a short post-run summary so the user gets feedback
    without having to immediately ``cat`` the induction report."""
    core = sum(1 for c in scored if c.classification == "core_business")
    supporting = sum(
        1 for c in scored if c.classification == "supporting_technical"
    )
    rejected = sum(
        1 for c in scored
        if c.classification not in ("core_business", "supporting_technical")
    )

    console.print(f"[green]Induced profile written to[/] {out_path}")
    console.print(
        f"  [bold]Candidates:[/] {len(scored)} total — "
        f"core_business={core}, "
        f"supporting_technical={supporting}, "
        f"rejected={rejected}"
    )

    selected = sorted(
        [
            c for c in scored
            if c.classification in ("core_business", "supporting_technical")
        ],
        key=lambda c: c.relevance_score,
        reverse=True,
    )[:5]
    if selected:
        console.print("  [bold]Top selected (by score):[/]")
        for c in selected:
            console.print(
                f"    - {c.label} "
                f"(score={c.relevance_score:.3f}, "
                f"classification={c.classification})"
            )


# ─── rebuild (profile induction workflow — stub orchestrator) ──────────────


@app.command(name="rebuild")
def rebuild(
    profile: Path = typer.Option(
        ..., "--profile",
        help=(
            "Directory containing the (reviewed and edited) induced "
            "profile. The profile is loaded and validated; the printed "
            "rebuild plan is parameterised by its profile_name."
        ),
    ),
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help=(
            "Per-domain workspace directory. Used in the printed plan as "
            "the conventional location for intermediate / output files."
        ),
    ),
    source_a: list[Path] = typer.Option(
        None, "--source-a",
        help=(
            "Source A extraction inputs. Accepted for forward-compat "
            "with the eventual orchestrator; informational only in the "
            "v1 stub."
        ),
    ),
    source_b: Path = typer.Option(
        None, "--source-b",
        help="Source B governance JSON. Same forward-compat note as --source-a.",
    ),
    source_c: Path = typer.Option(
        None, "--source-c",
        help="Source C schema JSON. Same forward-compat note as --source-a.",
    ),
    source_d: Path = typer.Option(
        None, "--source-d",
        help="Source D code / rules JSON. Same forward-compat note as --source-a.",
    ),
) -> None:
    """Print the rebuild plan for an induced / reviewed profile.

    Per the implementation plan, this command is a stub in v1: it
    loads and validates the supplied profile, then prints the chain
    of existing pipeline commands the user should run by hand to
    rebuild the fused dictionary with the reviewed profile.

    Direct orchestration of the chain (running ``extract-a``,
    ``fuse``, ``validate``, ``lint``, ``report`` in sequence
    in-process) is deferred to a follow-up task once the discovery
    flow is stable. The flag surface here matches what the
    orchestrator will eventually consume, so the CLI contract is
    stable across that change.
    """
    from .core.profile import ProfileError, load_profile

    console.print(
        "[yellow]Deprecation note:[/] `ontozense rebuild` is deprecated "
        "and will be removed in v2.0. Use `ontozense draft --plan` for "
        "the same effect."
    )

    try:
        loaded = load_profile(profile)
    except ProfileError as err:
        console.print(f"[red]Failed to load --profile {profile}:[/] {err}")
        raise typer.Exit(code=2)

    console.print(
        f"[bold]Rebuild plan for profile[/] '[cyan]{loaded.profile_name}[/]':"
    )
    print()
    print(
        "Run the following commands in order to rebuild the fused "
        "dictionary using the reviewed profile:"
    )
    print()
    # Command lines emitted via plain ``print`` so Rich's terminal-
    # width wrapping never breaks a step across visual lines (which
    # would also break copy-paste). Flags below match the exact
    # signatures of the corresponding commands in this file —
    # round-1 reviewer finding pinned ``ontozense fuse`` and
    # ``ontozense report`` against their actual flag sets.
    print(
        f"  1. ontozense extract-a <docs> "
        f"--profile {profile} "
        f"--json {domain_dir}/extract/source-a.json "
        f"--domain-dir {domain_dir}"
    )
    print(
        f"  2. ontozense fuse "
        f"--source-a {domain_dir}/extract/source-a.json "
        f"[--source-b {domain_dir}/source-b.json] "
        f"[--source-c {domain_dir}/source-c.json] "
        f"[--source-d {domain_dir}/source-d.json] "
        f"--output {domain_dir}/fused.json "
        f"--domain-dir {domain_dir}"
    )
    print(
        f"  3. ontozense validate {domain_dir}/fused.json "
        f"--profile {profile} "
        f"--domain-dir {domain_dir}"
    )
    print(
        f"  4. ontozense lint {domain_dir}/fused.json "
        f"--domain-dir {domain_dir}"
    )
    print(
        f"  5. ontozense report {domain_dir}/fused.json "
        f"--profile {profile} "
        f"--markdown {domain_dir}/report.md"
    )
    print()
    console.print(
        "[yellow]Note:[/] direct orchestration of this chain is "
        "deferred to a follow-up task. Run the commands manually "
        "for now and review the output between steps. The "
        "--source-a/-b/-c/-d flags are accepted for forward-compat "
        "but are informational only in this stub."
    )


# ─── survey (Stage 1 orchestrator) ───────────────────────────────────────────


@app.command(name="survey")
def survey(
    source_a: list[Path] = typer.Option(
        None, "--source-a",
        help=(
            "Source A input: a .md/.txt file (LLM-extracted), a "
            ".json file (pre-extracted source-a.json — reused as-is), "
            "a glob, or a directory (walked recursively). Repeatable."
        ),
    ),
    source_b: list[Path] = typer.Option(
        None, "--source-b",
        help=(
            "Source B governance JSON. File, glob, or directory. "
            "Repeatable."
        ),
    ),
    source_c: list[Path] = typer.Option(
        None, "--source-c",
        help=(
            "Source C schema input. Accepts .sql DDL files (parsed via "
            "sqlglot, v1.1 ingestion) or .json files (legacy v1.0 "
            "passthrough, no-op; full JSON ingestion is v1.2 work). "
            "File, glob, or directory; repeatable. Per-domain overrides "
            "via <domain-dir>/source-c.yaml. Mixed .sql + .json in one "
            "invocation is rejected."
        ),
    ),
    source_d: list[Path] = typer.Option(
        None, "--source-d",
        help=(
            "Source D code input. v1.1 ingests .py files via the "
            "deterministic AST extractor (classes, dataclasses, "
            "Pydantic/SQLAlchemy models, Enums, methods, validation "
            "functions). .sql/.js/.ts/.json are accepted by the CLI "
            "but currently ignored by the ingester (those languages "
            "are deferred per spec §13.2 #7). File, glob, or directory; "
            "repeatable. Per-domain overrides via "
            "<domain-dir>/source-d.yaml."
        ),
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional profile directory. Only its alias_map is "
            "consulted for light synonym normalisation."
        ),
    ),
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help=(
            "Per-domain workspace directory. Discovery artifacts are "
            "written under <domain_dir>/discovery/."
        ),
    ),
    model: str = typer.Option(
        "azure/gpt-5.4", "--model", "-m",
        help="LLM model identifier for the underlying extract-a step.",
    ),
) -> None:
    """Stage 1 of the semantic-layer journey.

    Survey your raw sources: extract from documents, merge in
    governance / schema / code, and produce a candidate graph for
    inspection. Writes three artifacts under <DOMAIN_DIR>/discovery/:

      - source-a.json      — concatenated extract-a output
      - candidate-graph.json
      - candidate-provenance.json

    Next step: ``ontozense draft`` (Stage 2).
    """
    _load_env()
    import json as _json

    from .core.candidate_graph import build_candidate_graph

    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)

    # ─── Source A: expand + partition ──
    try:
        a_files = _expand_source_paths(
            source_a or [],
            file_extensions={".md", ".txt", ".markdown", ".json"},
        )
    except _SourceLoadError as err:
        console.print(f"[red]Failed to enumerate --source-a paths:[/] {err}")
        raise typer.Exit(code=2)

    merged_a_concepts: list[dict] = []
    merged_a_rels: list[dict] = []
    for path in a_files:
        if path.suffix.lower() == ".json":
            # Pre-extracted source-a.json — load as-is.
            try:
                raw = _load_json(path)
            except _SourceLoadError as err:
                console.print(
                    f"[red]Failed to load --source-a {err.path}:[/] {err}"
                )
                raise typer.Exit(code=2)
            if not isinstance(raw, dict):
                console.print(
                    f"[red]--source-a {path}: must be a JSON object[/]"
                )
                raise typer.Exit(code=2)
            merged_a_concepts.extend(raw.get("concepts", []) or [])
            merged_a_rels.extend(raw.get("relationships", []) or [])
        else:
            # Doc — run extract-a and read its JSON output.
            extracted = _run_extract_a_for_survey(path, domain_dir, model)
            merged_a_concepts.extend(extracted.get("concepts", []) or [])
            merged_a_rels.extend(extracted.get("relationships", []) or [])

    merged_a: dict | None = None
    if merged_a_concepts or merged_a_rels:
        merged_a = {"concepts": merged_a_concepts, "relationships": merged_a_rels}
        (discovery_dir / "source-a.json").write_text(
            _json.dumps(merged_a, indent=2), encoding="utf-8",
        )

    # ─── Source B: expand + load ──
    try:
        b_files = _expand_source_paths(
            source_b or [], file_extensions={".json"},
        )
        merged_b = _merge_source_b(b_files) if b_files else None
    except _SourceLoadError as err:
        console.print(f"[red]Failed to load --source-b:[/] {err}")
        raise typer.Exit(code=2)

    # ─── Source C: expand .sql files + load per-domain config ──
    try:
        c_files = _expand_source_paths(
            source_c or [], file_extensions={".sql", ".json"},
        )
    except _SourceLoadError as err:
        console.print(
            f"[red]Failed to enumerate --source-c paths:[/] {err}"
        )
        raise typer.Exit(code=2)

    merged_c: dict | None = None
    if c_files:
        sql_files = [p for p in c_files if p.suffix.lower() == ".sql"]
        json_files = [p for p in c_files if p.suffix.lower() == ".json"]
        if sql_files and json_files:
            # Mixed input: hard error. v1.1 ingestion uses .sql DDL files;
            # .json remains as legacy v1.0 passthrough (deferred to v1.2
            # per spec §13.2 #6). Mixing both in one invocation is
            # ambiguous and would silently drop one set.
            console.print(
                "[red]--source-c received both .sql and .json inputs in "
                "the same invocation.[/]\n"
                "Source C accepts either .sql DDL files (v1.1 ingestion) "
                "OR .json passthrough (legacy v1.0 no-op), not both. "
                "Split into separate survey runs or drop one set."
            )
            raise typer.Exit(code=2)
        if sql_files:
            merged_c = {"files": [str(p) for p in sql_files]}
        elif json_files:
            # Legacy v1.0 JSON passthrough — JSON Source C ingestion is
            # deferred to v1.2 per spec §13.2 #6. Load to a no-op dict.
            merged_c = _load_source_passthrough(json_files)

    # ─── Source D: expand to file list (manifest) ──
    # The CLI accepts .py / .sql / .js / .ts / .json paths for Source D
    # and bundles them into a manifest of the shape {"files": [...]}.
    # SourceDIngester (v1.1) consumes .py files via the deterministic
    # AST extractor and silently ignores the other extensions — those
    # languages are deferred per spec §13.2 #7. The wider extension set
    # is preserved here so the manifest stays forward-compatible with
    # the v1.2+ multi-language ingester without another CLI signature
    # change.
    try:
        d_files = _expand_source_paths(
            source_d or [],
            file_extensions={".py", ".sql", ".js", ".ts", ".json"},
        )
    except _SourceLoadError as err:
        console.print(
            f"[red]Failed to enumerate --source-d paths:[/] {err}"
        )
        raise typer.Exit(code=2)
    merged_d = (
        {"files": [str(p) for p in d_files]} if d_files else None
    )

    # ─── Load per-domain source-d.yaml (if present) ──
    source_d_config: dict | None = None
    cfg_d_path = domain_dir / "source-d.yaml"
    if cfg_d_path.exists():
        from .core.ingest.filters import load_source_config, ConfigError
        try:
            source_d_config = load_source_config(cfg_d_path)
        except ConfigError as err:
            console.print(f"[red]Invalid source-d.yaml:[/] {err}")
            raise typer.Exit(code=2)

    # ─── Profile alias_map (light normalisation only) ──
    alias_map: dict[str, str] | None = None
    if profile is not None:
        from .core.profile import ProfileError, load_profile
        try:
            loaded = load_profile(profile)
            alias_map = dict(loaded.alias_map)
        except ProfileError as err:
            console.print(
                f"[red]Failed to load --profile {profile}:[/] {err}"
            )
            raise typer.Exit(code=2)

    # ─── Load per-domain source-c.yaml (if present) ──
    source_c_config: dict | None = None
    cfg_c_path = domain_dir / "source-c.yaml"
    if cfg_c_path.exists():
        from .core.ingest.filters import load_source_config, ConfigError
        try:
            source_c_config = load_source_config(cfg_c_path)
        except ConfigError as err:
            console.print(f"[red]Invalid source-c.yaml:[/] {err}")
            raise typer.Exit(code=2)

    # ─── Run discover ──
    graph = build_candidate_graph(
        source_a=merged_a,
        source_b=merged_b,
        source_c=merged_c,
        source_d=merged_d,
        alias_map=alias_map,
        source_c_config=source_c_config,
        source_d_config=source_d_config,
    )

    (discovery_dir / "candidate-graph.json").write_text(
        _json.dumps(graph.to_dict(), indent=2) + "\n", encoding="utf-8",
    )
    (discovery_dir / "candidate-provenance.json").write_text(
        _json.dumps({
            "concepts": [
                {
                    "candidate_id": c.candidate_id,
                    "label": c.label,
                    "provenance": [p.to_dict() for p in c.provenance],
                }
                for c in graph.concepts
            ],
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    # ─── PR1b: persist Source C / D field-level metadata ──
    # Property extraction Phase A. The candidate-graph drops per-column
    # SQL type / per-field Python type metadata; PR2's fusion engine
    # needs it to build typed Attribute records on each FusedElement.
    # We write parallel discovery files with the full typed contracts
    # so the lossy projection in candidate-graph.json doesn't constrain
    # downstream property emission. Skipped silently when the source
    # was not provided — preserves byte-identical behaviour for old
    # survey invocations (--source-c / --source-d absent).
    if c_files:
        sql_inputs = [p for p in c_files if p.suffix.lower() == ".sql"]
        if sql_inputs:
            from .core.source_c import (
                build_schema_from_sql_files,
                dump_source_c_json,
            )
            # PR1b r1 (Codex blocker 1): pass source_c_config so the
            # persistence path applies the same exclude_tables /
            # include_tables / exclude_columns + default suppressions
            # SourceCIngester enforces for the candidate-graph build.
            schema_result = build_schema_from_sql_files(
                sql_inputs,
                source_dir=str(sql_inputs[0].parent),
                config=source_c_config,
            )
            dump_source_c_json(
                schema_result, discovery_dir / "source-c.json",
            )
    if d_files:
        py_inputs = [p for p in d_files if p.suffix.lower() == ".py"]
        if py_inputs:
            from .core.source_d import (
                build_source_d_from_files,
                dump_source_d_json,
            )
            # PR1b r1 (Codex blocker 2): source_d_config carries
            # exclude_paths + class-level filters the builder now
            # mirrors against SourceDIngester (default path
            # suppressions + generated-code markers applied
            # unconditionally; YAML adds the user layer).
            sd_result = build_source_d_from_files(
                py_inputs, config=source_d_config,
            )
            dump_source_d_json(
                sd_result, discovery_dir / "source-d.json",
            )

    cross = sum(
        1 for c in graph.concepts
        if c.source_presence.get("A") and c.source_presence.get("B")
    )
    console.print(
        f"[green]Survey:[/] {len(graph.concepts)} candidates, "
        f"{len(graph.relationships)} relationships, "
        f"{cross} cross-source matches. "
        f"See {discovery_dir}."
    )
    console.print(_format_rule_summary(graph.concepts))


def _format_rule_summary(concepts: list) -> str:
    """Return a one-line rule-count summary grouped by rule_kind.

    Used by the ``survey`` command to surface rule extraction results
    without requiring the caller to inspect each concept manually.

    Examples::

        "Rules: 5 (derivation: 1, eligibility: 2, validation: 2)"
        "Rules: 0"
    """
    rule_concepts = [c for c in concepts if getattr(c, "artifact_kind", None) == "rule"]
    if not rule_concepts:
        return "Rules: 0"
    from collections import Counter
    by_kind: Counter = Counter(
        c.rule_payload.get("rule_kind", "unknown") if c.rule_payload else "unknown"
        for c in rule_concepts
    )
    kind_summary = ", ".join(
        f"{kind}: {count}"
        for kind, count in sorted(by_kind.items())
    )
    return f"Rules: {len(rule_concepts)} ({kind_summary})"


def _expand_source_paths(
    paths: list[Path],
    *,
    file_extensions: set[str],
) -> list[Path]:
    """Expand a list of file / glob / directory paths into a flat list
    of files matching the given extensions. Recurses into directories;
    expands glob patterns via :func:`glob.glob`.

    Glob detection looks for any of ``*``, ``?``, ``[`` in the path
    string — when the shell hasn't already expanded the pattern (e.g.
    the user passed it quoted, or they're on PowerShell which does
    not glob-expand most native-command arguments), the CLI does the
    expansion itself. An empty glob (no matches) is treated as a
    silent no-op, the same way an empty directory is treated.
    """
    out: list[Path] = []
    for p in paths:
        p_str = str(p)
        if any(ch in p_str for ch in "*?["):
            # Glob pattern — expand and walk results.
            matches = sorted(_glob.glob(p_str, recursive=True))
            for match in matches:
                m = Path(match)
                if m.is_file():
                    if m.suffix.lower() in file_extensions:
                        out.append(m)
                elif m.is_dir():
                    for child in sorted(m.rglob("*")):
                        if (
                            child.is_file()
                            and child.suffix.lower() in file_extensions
                        ):
                            out.append(child)
            # Empty glob → no-op (matches the "empty directory" rule).
            continue
        # Literal path (file or directory).
        if not p.exists():
            raise _SourceLoadError(p, f"path not found: {p}")
        if p.is_file():
            if p.suffix.lower() in file_extensions:
                out.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in file_extensions:
                    out.append(child)
    return out


def _run_extract_a_for_survey(
    doc_path: Path, domain_dir: Path, model: str,
) -> dict:
    """Invoke the existing extract-a pipeline programmatically and
    return its JSON output as a dict. Used by `survey` to extract
    from Source A documents on the fly.

    Implementation note: uses the existing DomainDocumentExtractor
    so behaviour matches `ontozense extract-a`.
    """
    from dataclasses import asdict

    from .extractors.domain_doc_extractor import DomainDocumentExtractor

    extractor = DomainDocumentExtractor(model=model)
    result = extractor.extract_from_file(doc_path)
    raw = asdict(result)
    # Reshape into the discovery-compatible {concepts, relationships}.
    return {
        "concepts": raw.get("concepts", []),
        "relationships": raw.get("relationships", []),
    }


# ─── draft (Stage 2 orchestrator) ────────────────────────────────────────────


@app.command(name="draft")
def draft(
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help="Per-domain workspace. Reads from <domain-dir>/discovery/.",
    ),
    output: Path = typer.Option(
        ..., "--output", "-o",
        help="Path for the draft OWL file.",
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional hand-authored profile directory. If given, "
            "induction is skipped and this profile is used directly."
        ),
    ),
    source_b: Path = typer.Option(
        None, "--source-b", "-b",
        help="Optional Source B governance JSON (single file).",
    ),
    source_c: Path = typer.Option(
        None, "--source-c", "-c",
        help=(
            "DEPRECATED — ignored. Source C is read from "
            "`discovery/candidate-graph.json` (produced by `survey`). "
            "Will be removed in a future release."
        ),
    ),
    source_d: Path = typer.Option(
        None, "--source-d", "-d",
        help="Optional Source D code input (single directory).",
    ),
    thresholds: Path = typer.Option(
        None, "--thresholds",
        help="Optional thresholds JSON (only used when inducing).",
    ),
    weights: Path = typer.Option(
        None, "--weights",
        help="Optional weights JSON (only used when inducing).",
    ),
    mode: str = typer.Option(
        "flag", "--mode",
        help='Validation mode: "flag" (annotate findings) or "filter".',
    ),
    format: str = typer.Option(
        "turtle", "--format",
        help='OWL serialisation: "turtle" (default) | "json-ld" | "owl-xml".',
    ),
    emit_rules: str = typer.Option(
        "annotations", "--emit-rules",
        help=(
            'Phase D rule projection. "annotations" (default) emits '
            'ontozense:businessRule annotation clusters for every '
            'BusinessRule. "none" matches pre-Phase-D behaviour. '
            '"restrictions", "swrl", "all" are reserved for Phase E '
            'and currently rejected.'
        ),
    ),
    property_induction: str = typer.Option(
        "off", "--property-induction",
        help=(
            'Phase B LLM property induction. "off" (default) is a '
            'no-op — pre-Phase-B behaviour preserved. "llm" runs '
            'the PR B1 dry-run scaffold: scans for eligible '
            'concepts and prints the budget plan. No LLM call, no '
            'cache file, no new disk artifacts. Real LLM call '
            'lands in PR B2.'
        ),
    ),
    property_induction_max_concepts: int = typer.Option(
        50, "--property-induction-max-concepts",
        help=(
            "Hard cap on eligible concepts processed in --property-"
            "induction llm mode. Sorted by Source A confidence "
            "descending; lower-confidence concepts skipped when "
            "over budget. Default 50."
        ),
    ),
    property_induction_max_calls: int = typer.Option(
        100, "--property-induction-max-calls",
        help=(
            "Hard cap on total LLM calls (including retries in PR "
            "B2). Default 100. In PR B1 this matches max-concepts "
            "because dry-run does not call the LLM."
        ),
    ),
    property_induction_token_budget: int = typer.Option(
        0, "--property-induction-token-budget",
        help=(
            "Optional total input-token cap. 0 (default) disables "
            "the cap. When set, processing stops once the "
            "cumulative input-token estimate exceeds N."
        ),
    ),
    property_induction_model: str = typer.Option(
        "azure/gpt-5.4", "--property-induction-model",
        help=(
            "LiteLLM model identifier for Phase B (PR B2). Matches "
            "the explicit default on extract-a / survey. Accepted "
            "but unused in PR B1 (no LLM call)."
        ),
    ),
    property_induction_refresh: bool = typer.Option(
        False, "--property-induction-refresh",
        help=(
            "Force cache miss for every eligible class in PR B2. "
            "Accepted but no-op in PR B1 (no cache exists yet)."
        ),
    ),
    plan: bool = typer.Option(
        False, "--plan",
        help="Print what would run; don't execute.",
    ),
) -> None:
    """Stage 2 of the semantic-layer journey.

    Score the candidate graph (or use your profile), fuse the
    sources, validate and lint, and emit a draft OWL ontology. The
    resulting ``draft.owl`` is the handoff artifact for an expert
    curator working in Ontology Playground, Protégé, or any OWL
    editor.
    """
    _load_env()
    from .core.profile import ProfileError, load_profile

    # Phase D (PR D1): --emit-rules validation. Phase D ships
    # "annotations" and "none" only. "restrictions", "swrl", "all"
    # are reserved for Phase E and rejected here so the user gets a
    # clear error rather than silent fallback. No doc link in the
    # message — Phase E design doc does not exist yet.
    _emit_rules_valid = {"annotations", "none"}
    _emit_rules_deferred = {"restrictions", "swrl", "all"}
    if emit_rules in _emit_rules_deferred:
        raise typer.BadParameter(
            f"--emit-rules {emit_rules!r} is not yet implemented "
            f"(queued for Phase E). Phase D supports only "
            f"{sorted(_emit_rules_valid)}.",
            param_hint="--emit-rules",
        )
    if emit_rules not in _emit_rules_valid:
        raise typer.BadParameter(
            f"--emit-rules must be one of "
            f"{sorted(_emit_rules_valid | _emit_rules_deferred)}; "
            f"got {emit_rules!r}.",
            param_hint="--emit-rules",
        )

    # Phase B (PR B1): --property-induction validation. B1 ships
    # only "off" and "llm" (dry-run). PR B2 may extend with future
    # modes but the contract today is exactly these two.
    _property_induction_valid = {"off", "llm"}
    if property_induction not in _property_induction_valid:
        raise typer.BadParameter(
            f"--property-induction must be one of "
            f"{sorted(_property_induction_valid)}; "
            f"got {property_induction!r}.",
            param_hint="--property-induction",
        )

    # Phase B (PR B1) — budget value validation.
    # Codex r1 blocker: typer parses these as plain int with no
    # lower bound, so a negative value would silently corrupt
    # BudgetEnforcer's index/slice logic. Enforce at the CLI
    # boundary so the contract is "hard cap, valid range only".
    # max_concepts / max_calls: must be >= 1 (0 == "disable
    # induction"; user has --property-induction off for that).
    # token_budget: 0 is the documented "unbounded" sentinel
    # (mapped to None below); negative is rejected.
    if property_induction_max_concepts < 1:
        raise typer.BadParameter(
            f"--property-induction-max-concepts must be >= 1; "
            f"got {property_induction_max_concepts}. "
            f"Use --property-induction off to disable induction.",
            param_hint="--property-induction-max-concepts",
        )
    if property_induction_max_calls < 1:
        raise typer.BadParameter(
            f"--property-induction-max-calls must be >= 1; "
            f"got {property_induction_max_calls}. "
            f"Use --property-induction off to disable induction.",
            param_hint="--property-induction-max-calls",
        )
    if property_induction_token_budget < 0:
        raise typer.BadParameter(
            f"--property-induction-token-budget must be >= 0 "
            f"(0 = unbounded); got "
            f"{property_induction_token_budget}.",
            param_hint="--property-induction-token-budget",
        )

    if plan:
        _print_draft_plan(domain_dir, profile, output)
        return

    discovery_dir = domain_dir / "discovery"
    candidate_graph_path = discovery_dir / "candidate-graph.json"
    if not candidate_graph_path.exists():
        console.print(
            f"[red]No candidate-graph.json under {discovery_dir}.[/]\n"
            "Run `ontozense survey` first."
        )
        raise typer.Exit(code=2)

    # ── Resolve profile ──
    induced_dir = domain_dir / "induced-profile"
    if profile is not None:
        try:
            loaded_profile_path = profile
            loaded_profile = load_profile(profile)
        except ProfileError as err:
            console.print(f"[red]Failed to load --profile {profile}:[/] {err}")
            raise typer.Exit(code=2)
    else:
        # Run induce-profile to produce one.
        from .core.discovery_contracts import CandidateConcept
        from .core.profile_induction import write_induced_profile
        from .core.relevance import (
            DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, score_candidates,
        )

        try:
            graph_raw = _load_json(candidate_graph_path)
        except _SourceLoadError as err:
            console.print(
                f"[red]Failed to load candidate graph {err.path}:[/] {err}"
            )
            raise typer.Exit(code=2)

        try:
            concepts = [
                CandidateConcept.from_dict(c)
                for c in graph_raw.get("concepts", [])
            ]
        except (TypeError, KeyError, ValueError, AttributeError) as err:
            console.print(
                f"[red]Malformed candidate graph {candidate_graph_path}:[/] "
                f"{err}"
            )
            raise typer.Exit(code=2)

        wmap: dict[str, float] | None = None
        tmap: dict[str, float] | None = None
        if weights is not None:
            try:
                wmap = _load_scoring_config(
                    weights,
                    required_keys=set(DEFAULT_WEIGHTS.keys()),
                    label="--weights",
                )
            except _SourceLoadError as err:
                console.print(
                    f"[red]Failed to load --weights {err.path}:[/] {err}"
                )
                raise typer.Exit(code=2)
        if thresholds is not None:
            try:
                tmap = _load_scoring_config(
                    thresholds,
                    required_keys=set(DEFAULT_THRESHOLDS.keys()),
                    label="--thresholds",
                )
            except _SourceLoadError as err:
                console.print(
                    f"[red]Failed to load --thresholds {err.path}:[/] {err}"
                )
                raise typer.Exit(code=2)

        scored = score_candidates(concepts, weights=wmap, thresholds=tmap)
        write_induced_profile(
            domain_name=domain_dir.name,
            candidates=scored,
            out_dir=induced_dir,
            weights=wmap,
            thresholds=tmap,
        )
        loaded_profile_path = induced_dir
        try:
            loaded_profile = load_profile(induced_dir)
        except ProfileError as err:
            console.print(
                f"[red]Failed to load induced profile {induced_dir}:[/] {err}"
            )
            raise typer.Exit(code=2)

    # ── Fuse → validate → lint → OWL ──
    from .core.lint import lint as run_lint
    from .core.owl_export import fused_to_owl
    from .core.validation import VALID_MODES, validate as run_validate

    if mode not in VALID_MODES:
        console.print(
            f"[red]Invalid --mode value:[/] {mode!r}. "
            f"Must be one of {sorted(VALID_MODES)}."
        )
        raise typer.Exit(code=2)

    source_a_path = discovery_dir / "source-a.json"
    fused = _run_fuse_for_draft(
        source_a_path, domain_dir / "fused.json",
        source_b=source_b,
        source_c=source_c,
        source_d=source_d,
        discovery_dir=discovery_dir,
    )

    # Phase B PR B2: real LLM property induction with cache.
    # ``off`` (default) is a complete no-op — never touches the
    # cache file, preserves Phase A regression byte-identity.
    # ``llm`` runs eligibility + budget, reads the cache, calls the
    # LLM for cache-miss concepts only, parses + merges the
    # attributes onto matching FusedElements, writes the cache.
    if property_induction == "llm":
        from .core.property_induction import Budget, induce_attributes

        token_budget = (
            property_induction_token_budget
            if property_induction_token_budget > 0
            else None
        )
        b_plan = induce_attributes(
            fused,
            model=property_induction_model,
            budget=Budget(
                max_concepts=property_induction_max_concepts,
                max_calls=property_induction_max_calls,
                token_budget=token_budget,
            ),
            dry_run=False,
            refresh=property_induction_refresh,
            discovery_dir=discovery_dir,
        )
        console.print(
            f"[bold blue]Property induction:[/] "
            f"{len(b_plan.eligible)} eligible concept(s), "
            f"{b_plan.cache_hits} cache hit(s), "
            f"{b_plan.cache_misses} LLM call(s), "
            f"{len(b_plan.skipped)} skipped by budget."
        )
        if b_plan.eligible:
            for concept in b_plan.eligible[:10]:
                attrs = b_plan.per_class.get(concept.class_uri, [])
                console.print(
                    f"    - {concept.element_name}  "
                    f"(confidence={concept.confidence:.2f}, "
                    f"attributes_induced={len(attrs)})"
                )
            if len(b_plan.eligible) > 10:
                console.print(
                    f"    ... and {len(b_plan.eligible) - 10} more"
                )
        for concept, reason in b_plan.skipped[:5]:
            console.print(
                f"  [yellow]{reason}[/] — {concept.element_name}"
            )
        if len(b_plan.skipped) > 5:
            console.print(
                f"  [yellow]... and {len(b_plan.skipped) - 5} more "
                "skipped[/]"
            )
        if property_induction_refresh:
            console.print(
                "  [dim]--property-induction-refresh: cache misses "
                "forced for every eligible concept.[/]"
            )

    validation_report = run_validate(fused, loaded_profile, mode=mode)
    lint_report = run_lint(fused)

    # Translate the user-facing format name "owl-xml" to rdflib's
    # "pretty-xml" serialiser. pretty-xml emits typed nodes
    # (<owl:Class>, <owl:ObjectProperty>) instead of the expanded
    # <rdf:Description> + <rdf:type> form that the default "xml"
    # serialiser produces — many OWL editors only recognise the typed
    # form. "turtle" and "json-ld" pass through unchanged.
    rdflib_format = "pretty-xml" if format == "owl-xml" else format

    owl_text = fused_to_owl(
        fused, profile=loaded_profile, format=rdflib_format,
        emit_rules=emit_rules,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(owl_text, encoding="utf-8")

    summary_path = domain_dir / "draft-summary.md"
    summary_path.write_text(
        _build_draft_summary(
            fused, validation_report, lint_report, loaded_profile_path,
        ),
        encoding="utf-8",
    )

    console.print(
        f"[green]Draft written to[/] {output}\n"
        f"  Summary: {summary_path}\n"
        f"Open in Ontology Playground or Protégé."
    )


def _run_fuse_for_draft(
    source_a_path: Path,
    output_path: Path,
    *,
    source_b: Path | None = None,
    source_c: Path | None = None,
    source_d: Path | None = None,
    discovery_dir: Path | None = None,
):
    """Run fusion programmatically and persist ``fused.json``.

    Mirrors the existing ``fuse`` CLI command's load + dispatch
    pattern. Source A is loaded from the canonical
    ``discovery/source-a.json``. Sources B / C / D are optional;
    when provided, each is loaded via the same helper the existing
    ``fuse`` command uses and passed to ``engine.fuse()`` so the
    Stage 2 contract — "fuse the resolved profile + all source
    inputs" — is satisfied.

    PR2 (property extraction): when ``discovery_dir`` is supplied,
    the helper reads ``discovery/source-c.json`` and
    ``discovery/source-d.json`` (the typed contracts written by
    ``survey`` in PR1b) and calls
    :func:`ontozense.core.fusion.attach_attributes_to_elements` so
    each FusedElement gains an ``attributes`` list. Missing
    discovery files are tolerated silently — the element-level
    fusion remains unchanged and ``attributes`` stays empty.
    """
    import json as _json
    from dataclasses import asdict

    from .core.fusion import FusionEngine, attach_attributes_to_elements

    sa_result = _load_source_a_json(source_a_path)

    sb_result = None
    sc_result = None
    sd_result = None

    if source_b is not None:
        from .extractors.governance_extractor import GovernanceExtractor
        sb_result = GovernanceExtractor().extract_from_file(source_b)
        console.print(
            f"[bold blue]Source B:[/] {len(sb_result.records)} governance "
            f"records from {source_b.name}"
        )

    if source_c is not None:
        # v1.1+: --source-c on `draft` is deprecated and ignored.
        # Source C contributions now reach the draft via
        # discovery/candidate-graph.json produced by `survey`.
        console.print(
            "[bold yellow][!] --source-c on `draft` is deprecated and ignored.[/]\n"
            "  Source C is now read from discovery/candidate-graph.json "
            "(produced by `ontozense survey`).\n"
            "  If you have a raw .sql schema, run "
            "`survey --source-c <file>.sql` first.\n"
            "  If you have a legacy SchemaResult JSON, run an adapter "
            "through `survey` instead.\n"
            "  This flag will be removed in a future release."
        )
        source_c = None

    if source_d is not None:
        from .extractors.code_extractor import CodeExtractor
        sd_result = CodeExtractor().extract_from_directory(source_d)
        console.print(
            f"[bold blue]Source D:[/] {len(sd_result.rules)} code rules "
            f"from {source_d}"
        )

    engine = FusionEngine()
    result = engine.fuse(
        source_a=[sa_result],
        source_b=sb_result,
        source_c=sc_result,
        source_d=sd_result,
    )

    # PR2: attach per-attribute properties from the deterministic
    # discovery artifacts. Missing files yield empty attributes; no
    # exception. Survey-time suppression (applied by PR1b) flows
    # naturally because we read what survey persisted.
    if discovery_dir is not None:
        from .core.source_c import (
            SourceCContractError,
            load_source_c_json,
        )
        from .core.source_d import (
            SourceDContractError,
            load_source_d_json,
        )

        schema = None
        sd_typed = None
        sc_path = discovery_dir / "source-c.json"
        sd_path = discovery_dir / "source-d.json"
        if sc_path.exists():
            try:
                schema = load_source_c_json(sc_path)
            except SourceCContractError as err:
                console.print(
                    f"[yellow]Source C discovery file invalid:[/] {err}\n"
                    f"  Attribute fusion will skip Source C contributions."
                )
        if sd_path.exists():
            try:
                sd_typed = load_source_d_json(sd_path)
            except SourceDContractError as err:
                console.print(
                    f"[yellow]Source D discovery file invalid:[/] {err}\n"
                    f"  Attribute fusion will skip Source D contributions."
                )
        attach_attributes_to_elements(
            result,
            schema=schema,
            source_d=sd_typed,
            governance=sb_result,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _json.dumps(asdict(result), indent=2, default=str),
        encoding="utf-8",
    )
    return result


def _build_draft_summary(fused, validation, lint, profile_path) -> str:
    """Compose the human-facing ``draft-summary.md``."""
    lines = [
        "# Draft summary",
        "",
        f"- Profile used: `{profile_path}`",
        f"- Elements: {len(fused.elements)}",
        f"- Relationships: {len(fused.relationships)}",
        f"- Validation: {validation.error_count} errors, "
        f"{validation.warning_count} warnings",
        f"- Lint findings: {len(lint.findings)} total "
        f"({lint.error_count} errors, {lint.warning_count} warnings)",
        "",
        "## What the curator should review first",
        "",
        "- Validation errors flagged above",
        "- Elements with low confidence (see fused.json)",
        "- Bridge concepts and orphan terms in the lint output",
    ]
    return "\n".join(lines) + "\n"


def _print_draft_plan(domain_dir: Path, profile: Path | None, output: Path) -> None:
    """Print the draft plan without executing.

    Uses ``print`` (not ``console.print``) so the output is stable
    across terminal widths — same approach as the legacy ``rebuild``
    command.
    """
    print(f"Plan for `ontozense draft` against {domain_dir}:")
    print()
    if profile is None:
        print("  1. induce-profile from discovery/candidate-graph.json")
    else:
        print(f"  1. use supplied profile: {profile}")
    print("  2. fuse discovery/source-a.json against the profile")
    print("  3. validate the fused dictionary (mode=flag)")
    print("  4. lint the fused dictionary")
    print(f"  5. export OWL to {output}")
    print("  6. write draft-summary.md alongside")


if __name__ == "__main__":
    app()
