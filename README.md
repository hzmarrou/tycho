# Ontozense

Extract, engineer, and refine ontologies from domain documents.

## Pipeline

```
Domain Documents → OntoGPT (SPIRES + LLM) → ontology_engineer (rdflib) → Playground JSON → Ontology Playground
```

## Quick Start

```bash
pip install -e ".[dev]"
ontozense extract document.md -o ontology.owl -j ontology.json
ontozense refine ontology.owl --validate --normalize
ontozense export ontology.owl -o playground.json
```
