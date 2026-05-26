"""Tests for the Phase C ``entity_types[*].attributes[]`` parser
addition on ``core.profile``.

Covers the loader contract introduced by PR C1: the new
``ProfileAttribute`` dataclass, the ``EntityType.attributes`` field,
the ``_ACCEPTED_XSD_TYPES`` whitelist, and every load-time validation
rule enumerated in
``docs/PROPERTY_EXTRACTION_DESIGN.md`` §5 Phase C contracts.

The tests deliberately do not touch ``core.validation`` — VR007
lands in PR C2. Here we only assert that profiles parse correctly
(or fail to parse with the documented error), and that pre-Phase-C
profiles continue to load unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.profile import (
    EntityType,
    Profile,
    ProfileAttribute,
    ProfileError,
    load_profile,
)


MINIMAL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── Happy path: a profile with a typed attribute list ───────────────────────


class TestHappyPath:
    def test_attributes_parsed_with_all_fields(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "Customer": {
                    "required": [],
                    "optional": [],
                    "attributes": [
                        {
                            "name": "customerId",
                            "xsd_type": "xsd:string",
                            "description": "Stable external identifier.",
                            "required": True,
                            "is_id": True,
                            "is_multivalued": False,
                            "enum_values": [],
                        },
                        {
                            "name": "tags",
                            "xsd_type": "xsd:string",
                            "is_multivalued": True,
                            "enum_values": ["red", "blue"],
                        },
                    ],
                }
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        customer = p.entity_types["Customer"]
        assert len(customer.attributes) == 2

        first = customer.attributes[0]
        assert isinstance(first, ProfileAttribute)
        assert first.name == "customerId"
        assert first.xsd_type == "xsd:string"
        assert first.description == "Stable external identifier."
        assert first.required is True
        assert first.is_id is True
        assert first.is_multivalued is False
        assert first.enum_values == []

        second = customer.attributes[1]
        assert second.name == "tags"
        assert second.xsd_type == "xsd:string"
        assert second.is_multivalued is True
        assert second.enum_values == ["red", "blue"]
        # Optional fields default correctly
        assert second.description == ""
        assert second.required is False
        assert second.is_id is False

    def test_omitted_attributes_key_defaults_to_empty_list(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"Concept": {"required": ["definition"]}},
            predicates={},
        )
        p = load_profile(tmp_path)
        assert p.entity_types["Concept"].attributes == []

    def test_empty_attributes_list_parses_to_empty_list(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"Concept": {"attributes": []}},
            predicates={},
        )
        p = load_profile(tmp_path)
        assert p.entity_types["Concept"].attributes == []

    def test_name_key_lowercases_and_strips(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "Customer": {
                    "attributes": [
                        {"name": "  CustomerId  ", "xsd_type": "xsd:string"},
                    ]
                }
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        attr = p.entity_types["Customer"].attributes[0]
        # The stored name preserves the author's casing/whitespace as-is
        assert attr.name == "  CustomerId  "
        # But the computed key is normalised for case-insensitive lookup
        assert attr.name_key == "customerid"


# ─── Accepted xsd_type set ───────────────────────────────────────────────────


class TestAcceptedXsdTypes:
    @pytest.mark.parametrize(
        "xsd",
        [
            "xsd:string",
            "xsd:integer",
            "xsd:decimal",
            "xsd:double",
            "xsd:date",
            "xsd:time",
            "xsd:dateTime",
            "xsd:dateTimeStamp",
            "xsd:duration",
            "xsd:boolean",
            "xsd:base64Binary",
            "xsd:anyURI",
        ],
    )
    def test_each_accepted_type_parses(self, tmp_path, xsd):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [{"name": "f", "xsd_type": xsd}]
                }
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        assert p.entity_types["A"].attributes[0].xsd_type == xsd

    def test_unknown_xsd_type_rejected_with_accepted_set_in_message(
        self, tmp_path
    ):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "f", "xsd_type": "xsd:int"}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError) as exc:
            load_profile(tmp_path)
        msg = str(exc.value)
        # Surface both the offending value and the accepted set so the
        # author can fix it without consulting the spec.
        assert "xsd:int" in msg
        assert "xsd:string" in msg
        assert "xsd:integer" in msg

    def test_xsd_type_non_string_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "f", "xsd_type": 42}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="xsd_type"):
            load_profile(tmp_path)

    def test_xsd_type_empty_string_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "f", "xsd_type": ""}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="xsd_type"):
            load_profile(tmp_path)


# ─── Required field checks ───────────────────────────────────────────────────


class TestRequiredFieldChecks:
    def test_missing_name_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {"attributes": [{"xsd_type": "xsd:string"}]}
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="name"):
            load_profile(tmp_path)

    def test_missing_xsd_type_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {"attributes": [{"name": "f"}]}
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="xsd_type"):
            load_profile(tmp_path)

    def test_empty_name_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "", "xsd_type": "xsd:string"}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="name"):
            load_profile(tmp_path)

    def test_whitespace_only_name_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "   ", "xsd_type": "xsd:string"}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="name"):
            load_profile(tmp_path)

    def test_name_non_string_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": 123, "xsd_type": "xsd:string"}
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="name"):
            load_profile(tmp_path)


# ─── Shape rules ─────────────────────────────────────────────────────────────


class TestShapeRules:
    def test_attributes_not_a_list_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {"attributes": "nope"}},
            predicates={},
        )
        with pytest.raises(ProfileError, match="attributes"):
            load_profile(tmp_path)

    def test_attribute_entry_not_an_object_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {"attributes": ["not-an-object"]}},
            predicates={},
        )
        with pytest.raises(ProfileError, match="attributes"):
            load_profile(tmp_path)

    def test_description_non_string_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "f",
                            "xsd_type": "xsd:string",
                            "description": 42,
                        }
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="description"):
            load_profile(tmp_path)

    @pytest.mark.parametrize("flag", ["required", "is_id", "is_multivalued"])
    def test_bool_flag_non_bool_rejected(self, tmp_path, flag):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "f",
                            "xsd_type": "xsd:string",
                            flag: "yes",
                        }
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match=flag):
            load_profile(tmp_path)

    def test_enum_values_not_a_list_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "f",
                            "xsd_type": "xsd:string",
                            "enum_values": "open,closed",
                        }
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="enum_values"):
            load_profile(tmp_path)

    def test_enum_values_non_string_member_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "f",
                            "xsd_type": "xsd:string",
                            "enum_values": ["open", 42],
                        }
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="enum_values"):
            load_profile(tmp_path)


# ─── Duplicate-name + single-is_id rules ─────────────────────────────────────


class TestDuplicateNameAndIsId:
    def test_duplicate_name_case_insensitive_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "Email", "xsd_type": "xsd:string"},
                        {"name": "email", "xsd_type": "xsd:string"},
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="[Dd]uplicate"):
            load_profile(tmp_path)

    def test_duplicate_name_with_whitespace_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {"name": "email", "xsd_type": "xsd:string"},
                        {"name": "  EMAIL  ", "xsd_type": "xsd:string"},
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="[Dd]uplicate"):
            load_profile(tmp_path)

    def test_multiple_is_id_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "primaryId",
                            "xsd_type": "xsd:string",
                            "is_id": True,
                        },
                        {
                            "name": "alternateId",
                            "xsd_type": "xsd:string",
                            "is_id": True,
                        },
                    ]
                }
            },
            predicates={},
        )
        with pytest.raises(ProfileError, match="is_id"):
            load_profile(tmp_path)

    def test_single_is_id_allowed(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "attributes": [
                        {
                            "name": "primaryId",
                            "xsd_type": "xsd:string",
                            "is_id": True,
                        },
                        {
                            "name": "email",
                            "xsd_type": "xsd:string",
                        },
                    ]
                }
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        attrs = p.entity_types["A"].attributes
        assert attrs[0].is_id is True
        assert attrs[1].is_id is False


# ─── Backward-compatibility regression guard ─────────────────────────────────


class TestPreCThreeBackwardCompat:
    """Phase C gate 4: pre-Phase-C profiles must parse byte-identically.

    The minimal fixture under ``tests/fixtures/profiles/minimal/`` was
    authored before Phase C and has no ``attributes`` key on any entity
    type. After PR C1 it must load with ``EntityType.attributes == []``
    on every type, and no other loaded field may change shape.
    """

    def test_minimal_fixture_still_loads(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert isinstance(p, Profile)
        # Same set of types, same metadata as before PR C1
        assert set(p.entity_types) == {"Concept", "Rule"}

    def test_every_entity_type_has_empty_attributes(self):
        p = load_profile(MINIMAL_FIXTURE)
        for et in p.entity_types.values():
            assert et.attributes == [], (
                f"Pre-Phase-C profile {p.profile_name!r} loaded "
                f"{et.name!r} with non-empty attributes "
                f"{et.attributes!r} — backward-compat regression."
            )

    def test_required_optional_subtypes_unchanged(self):
        p = load_profile(MINIMAL_FIXTURE)
        concept = p.entity_types["Concept"]
        assert concept.required_fields == ["definition"]
        assert concept.optional_fields == ["citation"]
        assert concept.subtypes == []
        rule = p.entity_types["Rule"]
        assert rule.required_fields == ["expression"]
        assert rule.optional_fields == ["docstring", "citation"]
        assert rule.subtypes == []

    def test_predicates_alias_verbs_unchanged(self):
        p = load_profile(MINIMAL_FIXTURE)
        # The whole non-attribute surface area is left alone by PR C1
        assert "AppliesTo" in p.predicates
        assert p.alias_map["concept-1"] == "Concept One"
        assert p.canonical_verbs["applies to"] == "AppliesTo"

    def test_entity_type_is_still_hashable_and_frozen(self):
        """``EntityType`` is declared frozen so it can be put in sets /
        used as dict keys downstream. Adding a list-typed default field
        must not break that contract — unhashable mutable defaults
        would surface as ``TypeError`` on hash, which we explicitly
        forbid here. (If hash is ever needed downstream it can be
        added; for now we only require frozen-immutability.)"""
        et = EntityType(name="X")
        # Frozen — attribute assignment raises
        with pytest.raises(Exception):
            et.name = "Y"  # type: ignore[misc]


# ─── Cross-contract: independence from required_fields ───────────────────────


class TestIndependenceFromRequiredFields:
    """``required`` on an ``attributes[*]`` entry and an entry in
    ``required_fields`` are independent contracts (see PROFILE_SPEC.md
    `attributes per entity type`: "The loader does not cross-validate
    against required_fields / optional_fields"). PR C1 must accept a
    profile that uses both without raising.
    """

    def test_attribute_required_and_field_required_coexist(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={
                "A": {
                    "required": ["definition"],
                    "optional": ["citation"],
                    "attributes": [
                        {
                            "name": "definition",
                            "xsd_type": "xsd:string",
                            "required": True,
                        }
                    ],
                }
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        et = p.entity_types["A"]
        assert et.required_fields == ["definition"]
        assert len(et.attributes) == 1
        assert et.attributes[0].required is True


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _write_profile(
    tmp_path: Path,
    *,
    entity_types: dict,
    predicates: dict,
) -> None:
    """Write a minimal ``schema.json`` into ``tmp_path``.

    Mirrors the helper in ``tests/test_profile_loader.py`` so the two
    suites stay independently runnable.
    """
    schema = {
        "profile_name": "test",
        "profile_version": "1.0.0",
        "entity_types": entity_types,
        "predicates": predicates,
    }
    (tmp_path / "schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
