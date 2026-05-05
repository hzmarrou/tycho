"""Deterministic ID generator for profile-driven extraction.

When a profile is loaded, every extracted entity gets a stable
identifier of the form::

    {entity_type_lower}_{normalized_label}_{hash6}

The same (type, label) tuple always produces the same ID, so:

  - Source A's "Carbon Emissions" and Source B's "Carbon Emissions"
    consolidate into one entity at fusion time.
  - The same document re-extracted on different days produces the
    same IDs (modulo what the LLM names the concepts).
  - Cross-document dedupe is straightforward — same ID = same entity.

The hash suffix protects against collisions when two distinct concepts
happen to normalise to the same label. With 6 hex chars (24 bits)
and ~10⁴ entities per domain, collision probability is < 1 in 10⁵.

This module is **profile-aware infrastructure**, not consumed yet by
any existing extractor. Phase 2+ wires it into Source A, then B/C/D.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata


# ─── Normalisation ───────────────────────────────────────────────────────────


def normalize_label(label: str) -> str:
    """Normalise an entity label into a stable lowercase token.

    Steps:
      1. Unicode NFKD normalisation (collapses ligatures, accents)
      2. Strip surrounding whitespace
      3. Lowercase
      4. Replace any whitespace, underscore, hyphen, slash, dot run with
         a single underscore
      5. Drop characters outside ``[a-z0-9_]``

    Examples
    --------
    >>> normalize_label("Carbon Emissions")
    'carbon_emissions'
    >>> normalize_label("Scope-1 Emissions")
    'scope_1_emissions'
    >>> normalize_label("CO₂ Equivalent")
    'co2_equivalent'
    >>> normalize_label("  GHG  Emissions  ")
    'ghg_emissions'
    """
    if not label:
        return ""

    # Step 1: NFKD normalise (collapses ligatures, separates accents)
    s = unicodedata.normalize("NFKD", label)

    # Drop combining marks (accents become base letter alone)
    s = "".join(c for c in s if not unicodedata.combining(c))

    # Steps 2 + 3
    s = s.strip().lower()

    # Step 4: separator runs → single underscore
    s = re.sub(r"[\s_\-/.]+", "_", s)

    # Step 5: drop anything outside [a-z0-9_]
    s = re.sub(r"[^a-z0-9_]", "", s)

    # Collapse repeated underscores from step 5 + trim edge underscores
    s = re.sub(r"_+", "_", s).strip("_")

    return s


# ─── ID generation ───────────────────────────────────────────────────────────


def compute_id(
    entity_type: str,
    label: str,
    *,
    hash_length: int = 6,
) -> str:
    """Compute a deterministic ID for an entity.

    Format: ``{entity_type_lower}_{normalized_label}_{hashN}``

    The hash is SHA-256 of ``"{type_lower}|{normalized_label}"`` truncated
    to ``hash_length`` hex characters. Stability:

      - Same (type, label) → same ID, every run, every machine.
      - Different label spelling → same ID after normalisation
        ("Carbon Emissions" == "carbon emissions" == "CARBON EMISSIONS").
      - Different type → different ID (so Metric:Default ≠ Concept:Default).

    Parameters
    ----------
    entity_type : str
        The profile-declared entity type (e.g. "Metric", "Industry").
        Case-insensitive — lowercased internally.
    label : str
        The entity's human label, as it appears in source content.
    hash_length : int
        Hash suffix length in hex chars. Default 6 (24 bits).
        Tests use 4 to force collisions; production uses 6+.

    Returns
    -------
    str
        Deterministic ID, e.g. ``"metric_carbon_emissions_a3f9c2"``.

    Raises
    ------
    ValueError
        If ``entity_type`` is empty or ``label`` normalises to empty.

    Examples
    --------
    >>> compute_id("Metric", "Carbon Emissions")
    'metric_carbon_emissions_8a4b3f'
    >>> compute_id("metric", "carbon emissions")  # case-insensitive
    'metric_carbon_emissions_8a4b3f'
    >>> compute_id("Concept", "Carbon Emissions") != compute_id("Metric", "Carbon Emissions")
    True
    """
    if not entity_type or not entity_type.strip():
        raise ValueError("entity_type must be non-empty")

    type_lower = entity_type.strip().lower()
    label_norm = normalize_label(label)

    if not label_norm:
        raise ValueError(
            f"label {label!r} normalises to empty string — cannot generate ID"
        )

    if hash_length < 4:
        raise ValueError(
            f"hash_length must be >= 4 (got {hash_length}) — shorter hashes "
            "have unacceptable collision risk"
        )

    digest = hashlib.sha256(
        f"{type_lower}|{label_norm}".encode("utf-8")
    ).hexdigest()[:hash_length]

    return f"{type_lower}_{label_norm}_{digest}"


def parse_id(entity_id: str) -> tuple[str, str, str]:
    """Inverse of compute_id: split an ID into its three parts.

    Returns ``(entity_type, normalized_label, hash)``.

    Useful for downstream tools that want to reason about ID components
    (e.g. group entities by type, find all entities with a given label
    across types).

    Raises
    ------
    ValueError
        If ``entity_id`` doesn't match the expected ``type_label_hash``
        shape.

    Examples
    --------
    >>> parse_id("metric_carbon_emissions_a3f9c2")
    ('metric', 'carbon_emissions', 'a3f9c2')
    """
    if not entity_id or "_" not in entity_id:
        raise ValueError(f"Not a valid identity-format ID: {entity_id!r}")

    parts = entity_id.rsplit("_", 1)
    if len(parts) != 2 or not _is_hex(parts[1]):
        raise ValueError(
            f"ID {entity_id!r} doesn't end with a hex hash suffix"
        )

    head, hash_part = parts
    if "_" not in head:
        raise ValueError(
            f"ID {entity_id!r} has no entity_type separator before label"
        )

    type_part, label_part = head.split("_", 1)
    return type_part, label_part, hash_part


def _is_hex(s: str) -> bool:
    """Check if a string is purely hex digits."""
    if not s:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False
