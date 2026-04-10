from .ontogpt_extractor import OntoGPTExtractor
from .django_schema import DjangoSchemaParser, SchemaResult
from .dd_extractor import (
    DataDictionaryExtractor,
    DataDictionaryResult,
    DataElement,
    FieldConfidence,
    Provenance,
)
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

__all__ = [
    "OntoGPTExtractor",
    "DjangoSchemaParser",
    "SchemaResult",
    # Legacy data-dictionary extractor (kept for compatibility)
    "DataDictionaryExtractor",
    "DataDictionaryResult",
    "DataElement",
    "FieldConfidence",
    "Provenance",
    # Source A — domain document extractor (replaces dd_extractor)
    "DomainDocumentExtractor",
    "DomainDocumentExtractionResult",
    "Concept",
    "Relationship",
    "DefinitionMatch",
    "extract_definitions_from_text",
    "extract_definitions_from_file",
]
