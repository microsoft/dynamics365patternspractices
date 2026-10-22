from app.writers.process import multiselect_field_labels


def test_multiselect_field_labels_from_ir() -> None:
    ir = {
        "process": {
            "fields": [
                {
                    "label": "Application family",
                    "multi_select": True,
                    "field_type": "PicklistString",
                },
                {"label": "Products", "multi_select": True, "field_type": "PicklistString"},
                {"label": "Module", "multi_select": False, "field_type": "PicklistString"},
                {"label": "Description", "multi_select": False, "field_type": "HTML"},
            ]
        }
    }
    assert multiselect_field_labels(ir) == {"Application family", "Products"}
