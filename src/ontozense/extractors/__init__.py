from .ontogpt_extractor import OntoGPTExtractor
# Source C dataclasses live in core.source_c — re-export here for
# back-compat. The Django parser (DjangoSchemaParser) has moved out
# of the package to ``adapters/django/``; users now feed a
# ``SchemaResult`` JSON file via ``ontozense fuse --source-c``.
from ..core.source_c import SchemaResult
from .domain_doc_extractor import (
    DomainDocumentExtractor,
    DomainDocumentExtractionResult,
    Concept,
    Relationship,
)
from .definitions_extractor import (
    DefinitionMatch,
    extract_definitions_from_text,
    extract_definitions_from_file,
)
from .governance_extractor import (
    GovernanceExtractor,
    GovernanceExtractionResult,
    GovernanceRecord,
    KNOWN_FIELDS as GOVERNANCE_KNOWN_FIELDS,
)
from .code_extractor import (
    CodeExtractor,
    CodeExtractionResult,
    CodeRule,
    CodeProvenance,
    PythonCodeExtractor,
    SqlCodeExtractor,
)


def __getattr__(name: str):
    """Compatibility shim for the pre-1.0 ``DjangoSchemaParser`` import path.

    Pre-1.0 callers wrote::

        from ontozense.extractors import DjangoSchemaParser

    Tycho 1.0 moved the parser out of the installed package to
    ``adapters/django/``. Rather than failing with a vanilla
    ``ImportError`` that doesn't tell anyone what to do, raise a
    targeted error pointing at the migration path.
    """
    if name == "DjangoSchemaParser":
        raise ImportError(
            "DjangoSchemaParser was moved to adapters/django/ in Tycho "
            "1.0; it is no longer part of the installed package. "
            "Either:\n"
            "  (1) import it from the bundled adapter: "
            "``sys.path.insert(0, 'adapters/django'); "
            "from django_schema import DjangoSchemaParser``\n"
            "  (2) run the adapter's CLI to produce Source C JSON: "
            "``python -m adapters.django.django_to_json <models-dir> "
            "--output source-c.json``, then feed it to "
            "``ontozense fuse --source-c source-c.json``.\n"
            "See adapters/django/README.md for details."
        )
    raise AttributeError(
        f"module 'ontozense.extractors' has no attribute {name!r}"
    )


__all__ = [
    "OntoGPTExtractor",
    "SchemaResult",
    # Source A — domain document extractor
    "DomainDocumentExtractor",
    "DomainDocumentExtractionResult",
    "Concept",
    "Relationship",
    "DefinitionMatch",
    "extract_definitions_from_text",
    "extract_definitions_from_file",
    # Source B — governance extractor (JSON reference file)
    "GovernanceExtractor",
    "GovernanceExtractionResult",
    "GovernanceRecord",
    "GOVERNANCE_KNOWN_FIELDS",
    # Source D — code extractor (deterministic layer)
    "CodeExtractor",
    "CodeExtractionResult",
    "CodeRule",
    "CodeProvenance",
    "PythonCodeExtractor",
    "SqlCodeExtractor",
]
