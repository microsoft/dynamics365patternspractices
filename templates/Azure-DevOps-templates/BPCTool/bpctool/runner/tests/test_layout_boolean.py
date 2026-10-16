from app.writers.layout import (
    _boolean_field_variants,
    _control_type,
    _wit_field_payload,
)


def test_boolean_wit_payload_uses_string_false():
    payload = _wit_field_payload(
        {
            "reference_name": "MSBPC.atleastone",
            "field_type": "Boolean",
            "required": "Yes",
            "default_value": "false",
        }
    )
    assert payload["referenceName"] == "MSBPC.atleastone"
    assert payload["defaultValue"] == "false"
    assert payload["requiredValue"] == "false"
    assert payload["required"] is True
    assert payload["visible"] is True


def test_control_types_match_reference_scripts():
    assert _control_type("Boolean") == "BooleanControl"
    assert _control_type("html") == "HtmlFieldControl"
    assert _control_type("String") == "Field"
    assert (
        _control_type(
            {"field_type": "PicklistString", "reference_name": "MSBPC.module", "label": "Module"}
        )
        == "PickListStringControl"
    )
    assert (
        _control_type(
            {
                "field_type": "PicklistString",
                "reference_name": "MSBPC.applicationfamily",
                "label": "Application family",
                "multi_select": True,
            }
        )
        == "MultivalueContribution"
    )
    assert (
        _control_type(
            {
                "field_type": "Identity",
                "reference_name": "System.AssignedTo",
            }
        )
        == "IdentityControl"
    )


def test_boolean_retry_variants_include_string_and_bool_false():
    variants = _boolean_field_variants("MSBPC.continuous")
    assert any(v.get("defaultValue") == "false" for v in variants)
    assert any(v.get("defaultValue") is False for v in variants)
    assert any(v.get("required") is False for v in variants)
