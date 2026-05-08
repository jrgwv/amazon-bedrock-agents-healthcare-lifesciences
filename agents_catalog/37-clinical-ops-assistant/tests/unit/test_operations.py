"""Unit tests for operations — mock vault_query, verify Pydantic models."""

from unittest.mock import patch

import pytest


@patch("operations.vault_query")
def test_get_study_by_name_found(mock_query):
    """Returns study when found."""
    import operations

    mock_query.return_value = [{
        "id": "123",
        "name__v": "BMS-001",
        "title__v": "Test Study",
        "status__v": "active__c",
        "phase__v": "Phase 3",
        "therapeutic_area__v": "Oncology",
        "sponsor__v": "BMS",
        "indication__v": "NSCLC",
        "planned_enrollment__v": 100,
        "actual_enrollment__v": 45,
        "start_date__v": "2024-01-15",
    }]

    result = operations.get_study_by_name({"studyName": "BMS-001"})
    assert result.study_name == "BMS-001"
    assert result.phase == "Phase 3"
    assert result.planned_enrollment == 100
    assert "study__v" in result.vault_url


@patch("operations.vault_query")
def test_get_study_by_name_not_found(mock_query):
    """Returns NOT FOUND when study doesn't exist."""
    import operations

    mock_query.return_value = []
    result = operations.get_study_by_name({"studyName": "NONEXISTENT"})
    assert result.title == "NOT FOUND"


@patch("operations.vault_query")
def test_list_studies_with_filters(mock_query):
    """Filters are applied to VQL query."""
    import operations

    mock_query.return_value = []
    operations.list_studies({"status": "active__c", "phase": "Phase 3", "limit": "10"})

    vql = mock_query.call_args[0][0]
    assert "status__v = 'active__c'" in vql
    assert "phase__v = 'Phase 3'" in vql
    assert "LIMIT 10" in vql


@patch("operations.vault_query")
def test_list_sites_for_study(mock_query):
    """Returns sites for a study."""
    import operations

    mock_query.return_value = [
        {"id": "1", "name__v": "Site A", "site_number__v": "001", "status__v": "active__c", "country__v": "US", "city__v": "Boston", "principal_investigator__v": "Dr. Smith"},
    ]

    result = operations.list_sites_for_study({"studyName": "BMS-001"})
    assert result.total_count == 1
    assert result.sites[0].site_name == "Site A"
    assert result.sites[0].country == "US"


@patch("operations.vault_query")
def test_search_documents(mock_query):
    """Document search returns formatted results."""
    import operations

    mock_query.return_value = [
        {"id": "99", "name__v": "IB v3", "document_number__v": "DOC-001", "type__v": "Investigator Brochure", "status__v": "Approved", "major_version_number__v": 3, "minor_version_number__v": 0, "last_modified_date__v": "2024-06-01"},
    ]

    result = operations.search_documents({"studyName": "BMS-001", "keyword": "IB"})
    assert result.total_count == 1
    assert result.documents[0].version == "3.0"
    assert result.documents[0].document_type == "Investigator Brochure"
