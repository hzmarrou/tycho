from .ontogpt_extractor import OntoGPTExtractor
from .django_schema import DjangoSchemaParser, SchemaResult
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
    "DjangoSchemaParser",
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
