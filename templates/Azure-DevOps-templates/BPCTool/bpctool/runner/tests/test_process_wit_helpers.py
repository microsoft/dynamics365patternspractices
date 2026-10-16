from app.writers.process import (
    _is_system_reference,
    _resolve_existing_wit,
    _short_reference_name,
    _index_process_wits,
)


def test_system_reference_helpers():
    assert _is_system_reference("Microsoft.VSTS.WorkItemTypes.Bug")
    assert not _is_system_reference("MSBPCTemplate.Process")
    assert _short_reference_name("Microsoft.VSTS.WorkItemTypes.TestCase") == "TestCase"


def test_index_prefers_lookup_by_name_and_short_ref():
    index = _index_process_wits(
        [
            {
                "name": "Bug",
                "referenceName": "MSBPCTemplate.Bug",
                "customization": "inherited",
            }
        ]
    )
    assert _resolve_existing_wit(index, "Bug", "Microsoft.VSTS.WorkItemTypes.Bug")["name"] == "Bug"
    assert index["bug"]["referenceName"] == "MSBPCTemplate.Bug"
