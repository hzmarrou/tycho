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
