"""Validation stage — runs after fusion, before lint, in profile mode.

Phase 4 of the constrained-extraction upgrade. Takes a fused output
(``FusionResult``) and a loaded ``Profile`` and verifies the data
conforms to the profile's schema. Six structural rules borrowed from
OntoMetric's stage 3 validation, plus VR007 added in Phase C
(profile-declared typed attributes):

  VR001  Entity uniqueness                       (error)
  VR002  Type membership                         (error)
  VR003  Required fields populated               (warning)
  VR004  Predicate vocabulary                    (error)
  VR005  Predicate domain matching               (warning)
  VR006  Cardinality respect                     (warning)
  VR007  Required attributes present             (warning)

Two operating modes:

  ``flag``  (default)  — annotate findings, keep all entities/relationships
  ``filter``           — drop entities that fail VR001/VR002 errors and
                         cascade-drop relationships referencing them;
                         drop relationships that fail VR004

VR007 is annotate-only in both modes (matches VR003's sibling
"required field missing" semantics).

Phase 4 is **profile-required**: validating a fused output without a
profile is meaningless because the rules are profile-defined. The CLI
``ontozense validate`` command rejects calls without ``--profile``.

Semantic validation (LLM-as-judge) is deferred to a follow-up
commit per the agreed Phase 4 scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .fusion import FusedElement, FusedRelationship, FusionResult, normalise_name
from .profile import Profile


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class ValidationFinding:
    """One issue found by the validator.

    Mirrors the shape of LintFinding so downstream tooling can treat
    validation and lint findings uniformly when needed.
    """
    rule_id: str          # "VR001" through "VR007"
    severity: str         # "error" / "warning" / "info"
    target_kind: str      # "entity" / "relationship"
    target_id: str        # entity ID, or "subject_id->predicate->object_id"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """The output of running validation on a fused knowledge base."""
    findings: list[ValidationFinding] = field(default_factory=list)
    elements: list[FusedElement] = field(default_factory=list)
    relationships: list[FusedRelationship] = field(default_factory=list)
    profile_name: str = ""
    profile_version: str = ""
    mode: str = "flag"
    cascade_filtered_entities: int = 0
    cascade_filtered_relationships: int = 0
    timestamp: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return out

    def by_rule(self, rule_id: str) -> list[ValidationFinding]:
        return [f for f in self.findings if f.rule_id == rule_id]

    def by_severity(self, severity: str) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity == severity]


# ─── Public entry point ──────────────────────────────────────────────────────


VALID_MODES = {"flag", "filter"}


def validate(
    fusion_result: FusionResult,
    profile: Profile,
    *,
    mode: str = "flag",
) -> ValidationResult:
    """Run all 6 structural validation rules on a fused result.

    Parameters
    ----------
    fusion_result :
        Output of ``ontozense.core.fusion.FusionEngine.fuse()`` — a list
        of ``FusedElement`` plus relationships.
    profile :
        Loaded profile from ``ontozense.core.profile.load_profile()``.
        Required: validation is meaningless without a profile.
    mode :
        ``"flag"`` (default): annotate findings, keep all data.
        ``"filter"``: drop entities that fail VR001/VR002 errors and
        cascade-drop their relationships; drop relationships that fail
        VR004 (unknown predicate).

    Returns
    -------
    ValidationResult
        Findings + post-validation elements/relationships + cascade
        counts. Caller writes the validated JSON; lint runs after.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}"
        )

    result = ValidationResult(
        profile_name=profile.profile_name,
        profile_version=profile.profile_version,
        mode=mode,
        timestamp=datetime.utcnow().isoformat(),
    )

    elements = list(fusion_result.elements)
    relationships = list(fusion_result.relationships)

    # Run rules in order. VR001-VR002 may drop entities (in filter mode);
    # VR003 only annotates. VR004 may drop relationships. VR005-VR006
    # only annotate. VR007 (Phase C) is annotate-only in both modes.
    elements = _check_vr001_uniqueness(elements, result, mode)
    elements = _check_vr002_type_membership(elements, profile, result, mode)
    _check_vr003_required_fields(elements, profile, result)
    _check_vr007_required_attributes(elements, profile, result)

    # Build the surviving entity ID set BEFORE running relationship checks
    # so cascade filtering can drop dangling relationships.
    surviving_ids = {_entity_id(el) for el in elements}

    relationships = _check_vr004_predicate_vocabulary(
        relationships, profile, result, mode,
    )
    _check_vr005_predicate_domains(
        relationships, elements, profile, result,
    )
    _check_vr006_cardinality(relationships, profile, result)

    # Cascade filter: drop any relationship referencing a dropped entity
    # (filter mode only — flag mode keeps the dangling reference)
    if mode == "filter":
        before = len(relationships)
        relationships = [
            r for r in relationships
            if _resolve_endpoint_id(r.subject, elements) in surviving_ids
            and _resolve_endpoint_id(r.object, elements) in surviving_ids
        ]
        result.cascade_filtered_relationships = before - len(relationships)

    result.elements = elements
    result.relationships = relationships
    return result


# ─── VR001: Entity uniqueness ────────────────────────────────────────────────


def _check_vr001_uniqueness(
    elements: list[FusedElement],
    result: ValidationResult,
    mode: str,
) -> list[FusedElement]:
    """Each entity ID must be unique. Duplicates are an error.

    In filter mode, keep the first occurrence and drop the rest
    (cascade drops happen after VR002).
    """
    seen: dict[str, FusedElement] = {}
    duplicates: list[FusedElement] = []

    for el in elements:
        eid = _entity_id(el)
        if not eid:
            continue  # Empty ID skipped — caught by VR002 instead
        if eid in seen:
            duplicates.append(el)
            result.findings.append(
                ValidationFinding(
                    rule_id="VR001",
                    severity="error",
                    target_kind="entity",
                    target_id=eid,
                    message=(
                        f"Entity {eid!r} appears more than once. "
                        f"Names: {seen[eid].element_name!r} and "
                        f"{el.element_name!r}."
                    ),
                    details={
                        "duplicate_of": seen[eid].element_name,
                        "current_name": el.element_name,
                    },
                )
            )
        else:
            seen[eid] = el

    if mode == "filter" and duplicates:
        # Use object identity (id()) not value-equality. FusedElement is
        # a default @dataclass with field-based __eq__, so two duplicates
        # with identical field values would compare equal — a value-based
        # `not in duplicates` filter would then drop the kept first
        # occurrence too. Identity-based filtering preserves "first wins".
        dup_object_ids = {id(d) for d in duplicates}
        kept = [el for el in elements if id(el) not in dup_object_ids]
        result.cascade_filtered_entities += len(duplicates)
        return kept
    return elements


# ─── VR002: Type membership ──────────────────────────────────────────────────


def _check_vr002_type_membership(
    elements: list[FusedElement],
    profile: Profile,
    result: ValidationResult,
    mode: str,
) -> list[FusedElement]:
    """Each entity must have an entity_type declared in the profile.

    Empty entity_type is an error (the source extractor couldn't
    determine it; Phase 4 surfaces the gap). Unknown entity_type
    (not in profile.entity_types or any subtype) is also an error.
    """
    invalid: list[FusedElement] = []

    for el in elements:
        # In profile mode, every entity should have a type. We read it
        # from extra_fields["entity_type"] if present (FusedElement
        # doesn't have a typed entity_type field — Phase 5 will
        # consolidate this).
        entity_type = el.extra_fields.get("entity_type", "")

        if not entity_type:
            result.findings.append(
                ValidationFinding(
                    rule_id="VR002",
                    severity="error",
                    target_kind="entity",
                    target_id=_entity_id(el) or el.element_name,
                    message=(
                        f"Entity {el.element_name!r} has no entity_type. "
                        f"In constrained mode every entity must declare "
                        f"a type from the profile."
                    ),
                    details={"element_name": el.element_name},
                )
            )
            invalid.append(el)
            continue

        if not profile.is_known_type(entity_type):
            result.findings.append(
                ValidationFinding(
                    rule_id="VR002",
                    severity="error",
                    target_kind="entity",
                    target_id=_entity_id(el) or el.element_name,
                    message=(
                        f"Entity {el.element_name!r} has unknown "
                        f"entity_type {entity_type!r}. Profile "
                        f"{profile.profile_name!r} declares: "
                        f"{sorted(profile.entity_types.keys())}."
                    ),
                    details={
                        "element_name": el.element_name,
                        "entity_type": entity_type,
                        "known_types": sorted(profile.entity_types.keys()),
                    },
                )
            )
            invalid.append(el)

    if mode == "filter" and invalid:
        # Identity-based filter — same reasoning as VR001.
        invalid_object_ids = {id(x) for x in invalid}
        kept = [el for el in elements if id(el) not in invalid_object_ids]
        result.cascade_filtered_entities += len(invalid)
        return kept
    return elements


# ─── VR003: Required fields ──────────────────────────────────────────────────


def _check_vr003_required_fields(
    elements: list[FusedElement],
    profile: Profile,
    result: ValidationResult,
) -> None:
    """Every entity of a known type must have its required fields populated.

    Required fields are looked up first on the FusedElement's typed
    attributes (definition, is_critical, etc.), then in extra_fields.
    Empty / None / "" values count as missing.
    """
    for el in elements:
        entity_type = el.extra_fields.get("entity_type", "")
        if not entity_type:
            continue  # VR002 handled

        et = profile.get_entity_type(entity_type)
        if et is None:
            continue  # VR002 handled

        missing: list[str] = []
        for req in et.required_fields:
            if not _field_value_present(el, req):
                missing.append(req)

        if missing:
            result.findings.append(
                ValidationFinding(
                    rule_id="VR003",
                    severity="warning",
                    target_kind="entity",
                    target_id=_entity_id(el) or el.element_name,
                    message=(
                        f"Entity {el.element_name!r} (type "
                        f"{entity_type!r}) is missing required field(s): "
                        f"{missing}."
                    ),
                    details={
                        "element_name": el.element_name,
                        "entity_type": entity_type,
                        "missing_fields": missing,
                    },
                )
            )


# ─── VR004: Predicate vocabulary ─────────────────────────────────────────────


def _check_vr004_predicate_vocabulary(
    relationships: list[FusedRelationship],
    profile: Profile,
    result: ValidationResult,
    mode: str,
) -> list[FusedRelationship]:
    """Every relationship's predicate must be in the profile's vocabulary."""
    invalid: list[FusedRelationship] = []

    for rel in relationships:
        if not profile.is_known_predicate(rel.predicate):
            result.findings.append(
                ValidationFinding(
                    rule_id="VR004",
                    severity="error",
                    target_kind="relationship",
                    target_id=f"{rel.subject}->{rel.predicate}->{rel.object}",
                    message=(
                        f"Predicate {rel.predicate!r} is not in profile "
                        f"{profile.profile_name!r}'s vocabulary. "
                        f"Allowed: {sorted(profile.predicates.keys())}."
                    ),
                    details={
                        "predicate": rel.predicate,
                        "known_predicates": sorted(profile.predicates.keys()),
                        "subject": rel.subject,
                        "object": rel.object,
                    },
                )
            )
            invalid.append(rel)

    if mode == "filter" and invalid:
        # Identity-based filter — FusedRelationship is also a default
        # @dataclass and would otherwise drop value-equal kept entries.
        invalid_object_ids = {id(r) for r in invalid}
        return [r for r in relationships if id(r) not in invalid_object_ids]
    return relationships


# ─── VR005: Predicate domain matching ────────────────────────────────────────


def _check_vr005_predicate_domains(
    relationships: list[FusedRelationship],
    elements: list[FusedElement],
    profile: Profile,
    result: ValidationResult,
) -> None:
    """Each relationship's subject/object types must match the predicate."""
    for rel in relationships:
        if not profile.is_known_predicate(rel.predicate):
            continue  # VR004 already flagged

        # Find the canonical predicate name (case-insensitive lookup)
        pred_name = next(
            (p for p in profile.predicates if p.lower() == rel.predicate.lower()),
            rel.predicate,
        )
        pred = profile.predicates[pred_name]

        subj_type = _entity_type_for(rel.subject, elements)
        obj_type = _entity_type_for(rel.object, elements)

        # Skip if we can't determine endpoint types (VR002 already flagged)
        if not subj_type or not obj_type:
            continue

        if pred.subject_types and subj_type not in pred.subject_types:
            # Allow subtypes: if subj_type is a subtype of an allowed
            # type, that's fine.
            if not _is_or_extends(subj_type, pred.subject_types, profile):
                result.findings.append(
                    ValidationFinding(
                        rule_id="VR005",
                        severity="warning",
                        target_kind="relationship",
                        target_id=f"{rel.subject}->{pred_name}->{rel.object}",
                        message=(
                            f"Predicate {pred_name!r} expects subject types "
                            f"{pred.subject_types}, got {subj_type!r}."
                        ),
                        details={
                            "predicate": pred_name,
                            "expected_subject_types": pred.subject_types,
                            "actual_subject_type": subj_type,
                        },
                    )
                )

        if pred.object_types and obj_type not in pred.object_types:
            if not _is_or_extends(obj_type, pred.object_types, profile):
                result.findings.append(
                    ValidationFinding(
                        rule_id="VR005",
                        severity="warning",
                        target_kind="relationship",
                        target_id=f"{rel.subject}->{pred_name}->{rel.object}",
                        message=(
                            f"Predicate {pred_name!r} expects object types "
                            f"{pred.object_types}, got {obj_type!r}."
                        ),
                        details={
                            "predicate": pred_name,
                            "expected_object_types": pred.object_types,
                            "actual_object_type": obj_type,
                        },
                    )
                )


# ─── VR006: Cardinality ──────────────────────────────────────────────────────


def _check_vr006_cardinality(
    relationships: list[FusedRelationship],
    profile: Profile,
    result: ValidationResult,
) -> None:
    """Cardinality semantics:

      ``1:1`` — each subject has at most 1 distinct object via this
                predicate; each object has at most 1 distinct subject.
      ``1:N`` — each object has at most 1 distinct subject (a 1:N B
                means each B traces back to one A).
      ``N:1`` — each subject has at most 1 distinct object.
      ``N:N`` — no constraint.
    """
    # Group relationships by predicate
    by_pred: dict[str, list[FusedRelationship]] = {}
    for rel in relationships:
        if not profile.is_known_predicate(rel.predicate):
            continue
        # Normalise to canonical predicate name
        canon = next(
            (p for p in profile.predicates if p.lower() == rel.predicate.lower()),
            rel.predicate,
        )
        by_pred.setdefault(canon, []).append(rel)

    for pred_name, rels in by_pred.items():
        pred = profile.predicates[pred_name]
        cardinality = pred.cardinality

        # Count distinct objects per subject and distinct subjects per object
        subj_to_objs: dict[str, set[str]] = {}
        obj_to_subjs: dict[str, set[str]] = {}
        for r in rels:
            subj_to_objs.setdefault(r.subject, set()).add(r.object)
            obj_to_subjs.setdefault(r.object, set()).add(r.subject)

        # Check subject side (constraint depending on cardinality)
        if cardinality in ("1:1", "N:1"):
            for subj, objs in subj_to_objs.items():
                if len(objs) > 1:
                    result.findings.append(
                        ValidationFinding(
                            rule_id="VR006",
                            severity="warning",
                            target_kind="relationship",
                            target_id=f"{subj}->{pred_name}->*",
                            message=(
                                f"Predicate {pred_name!r} has cardinality "
                                f"{cardinality!r}: subject {subj!r} should "
                                f"map to at most 1 object, but maps to "
                                f"{len(objs)}: {sorted(objs)}."
                            ),
                            details={
                                "predicate": pred_name,
                                "cardinality": cardinality,
                                "subject": subj,
                                "object_count": len(objs),
                                "objects": sorted(objs),
                            },
                        )
                    )

        # Check object side
        if cardinality in ("1:1", "1:N"):
            for obj, subjs in obj_to_subjs.items():
                if len(subjs) > 1:
                    result.findings.append(
                        ValidationFinding(
                            rule_id="VR006",
                            severity="warning",
                            target_kind="relationship",
                            target_id=f"*->{pred_name}->{obj}",
                            message=(
                                f"Predicate {pred_name!r} has cardinality "
                                f"{cardinality!r}: object {obj!r} should "
                                f"map to at most 1 subject, but maps to "
                                f"{len(subjs)}: {sorted(subjs)}."
                            ),
                            details={
                                "predicate": pred_name,
                                "cardinality": cardinality,
                                "object": obj,
                                "subject_count": len(subjs),
                                "subjects": sorted(subjs),
                            },
                        )
                    )


# ─── VR007: Required attributes present (Phase C) ────────────────────────────


def _check_vr007_required_attributes(
    elements: list[FusedElement],
    profile: Profile,
    result: ValidationResult,
) -> None:
    """Every entity of a known type must carry an extracted ``Attribute``
    for each profile-declared ``attributes[*]`` entry marked
    ``required: true``.

    Presence definition (design §5 Phase C contracts): a profile-declared
    required attribute with ``name_key = K`` is present on element ``el``
    iff there exists at least one ``Attribute`` ``a`` in ``el.attributes``
    such that ``a.name.strip().lower() == K``. Empty-name attributes
    never count as present. XSD type, multivaluedness, value-set
    membership, and ``is_id`` flag agreement are **not** part of the
    presence check.

    B-LLM-sourced attributes (``field_provenance[*].source == "B-LLM"``)
    count toward presence identically to deterministic Source C/D/B
    attributes — VR007 is a structural rule, not a confidence rule.

    One finding is emitted per element per missing required attribute
    name (matches VR005's per-relationship granularity rather than
    VR003's one-finding-with-a-list shape).

    No-op when the profile declares no ``attributes`` on any entity
    type (the typical pre-Phase-C profile shape).
    """
    for el in elements:
        entity_type = el.extra_fields.get("entity_type", "")
        if not entity_type:
            continue  # VR002 handled

        et = profile.get_entity_type(entity_type)
        if et is None:
            continue  # VR002 handled

        if not et.attributes:
            continue  # nothing declared for this type — VR007 no-op

        # Build the set of name_keys actually carried by the element's
        # extracted attributes. Empty names never satisfy any required
        # declaration (design §5 "Present" definition).
        extracted_keys: set[str] = set()
        for attr in el.attributes:
            key = (attr.name or "").strip().lower()
            if key:
                extracted_keys.add(key)

        for pa in et.attributes:
            if not pa.required:
                continue
            if pa.name_key in extracted_keys:
                continue
            result.findings.append(
                ValidationFinding(
                    rule_id="VR007",
                    severity="warning",
                    target_kind="entity",
                    target_id=_entity_id(el) or el.element_name,
                    message=(
                        f"Entity {el.element_name!r} (type "
                        f"{entity_type!r}) is missing required "
                        f"attribute(s): {[pa.name]}."
                    ),
                    details={
                        "element_name": el.element_name,
                        "entity_type": entity_type,
                        "missing_required_attributes": [pa.name],
                    },
                )
            )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _fallback_id(el: FusedElement) -> str:
    """When an element has no deterministic ID (profile gap), use the
    normalised element_name as a stable surrogate."""
    return normalise_name(el.element_name)


def _resolve_endpoint_id(endpoint: str, elements: list[FusedElement]) -> str:
    """Map a relationship endpoint (subject/object string) to an entity ID.

    The endpoint may be an entity ID directly, an element_name, or a
    name that needs alias resolution. We match by ID first, then by
    normalised name.
    """
    # Direct ID match
    for el in elements:
        eid = _entity_id_only(el)
        if eid and eid == endpoint:
            return eid
    # Normalised name match
    target = normalise_name(endpoint)
    for el in elements:
        if normalise_name(el.element_name) == target:
            return _entity_id(el)
    # Couldn't resolve; return the normalised endpoint itself as a
    # surrogate so cascade filtering produces consistent comparisons.
    return target


def _entity_id(el: FusedElement) -> str:
    """The entity ID, falling back to the normalised element_name."""
    eid = el.extra_fields.get("id", "")
    return eid or _fallback_id(el)


def _entity_id_only(el: FusedElement) -> str:
    """The deterministic ID, or "" if no profile-mode ID was assigned."""
    return el.extra_fields.get("id", "")


def _entity_type_for(endpoint: str, elements: list[FusedElement]) -> str:
    """Find the entity_type for a relationship endpoint, or "" if unknown."""
    target = normalise_name(endpoint)
    for el in elements:
        if (
            _entity_id_only(el) == endpoint
            or normalise_name(el.element_name) == target
        ):
            return el.extra_fields.get("entity_type", "")
    return ""


def _is_or_extends(
    type_name: str,
    allowed_types: list[str],
    profile: Profile,
) -> bool:
    """True if ``type_name`` is in ``allowed_types`` directly or via subtype.

    Example: type_name="DirectMetric" with allowed_types=["Metric"] is
    True because DirectMetric is a subtype of Metric in the profile.
    """
    if type_name in allowed_types:
        return True
    et = profile.get_entity_type(type_name)
    if et is None:
        return False
    # If the resolved EntityType.name matches an allowed type, the
    # query is a subtype of that type
    return et.name in allowed_types


def _field_value_present(el: FusedElement, field_name: str) -> bool:
    """Whether ``field_name`` has a non-empty value on the element.

    Looks at the typed attributes first (definition, citation,
    is_critical, etc.) and then in extra_fields.
    """
    # FusedElement's typed fields that VR003 might check
    typed_fields = {
        "element_name", "domain_name", "definition", "is_critical",
        "citation", "data_type", "enum_values", "business_rules",
    }
    if field_name in typed_fields:
        v = getattr(el, field_name, None)
        if isinstance(v, bool):
            return True  # is_critical: bool is always "set"
        if isinstance(v, (list, dict)):
            return bool(v)
        return bool(v) if v is not None else False
    # Otherwise look in extra_fields
    v = el.extra_fields.get(field_name)
    if v is None:
        return False
    if isinstance(v, (list, dict)):
        return bool(v)
    if isinstance(v, str):
        return bool(v.strip())
    return True
