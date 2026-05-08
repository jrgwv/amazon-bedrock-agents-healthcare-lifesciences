"""Operations mapping to OpenAPI schema operationIds.

Each function takes params from the Bedrock event and returns a Pydantic model.
# TODO: confirm Vault object/field names with customer's Vault configuration.
"""

import os

from models import (
    Document, DocumentList, Milestone, MilestoneList,
    Site, SiteList, Study, StudyList,
)
from vault_client import vault_query

_VAULT_BASE_URL = os.environ.get("VAULT_BASE_URL", "")


def _vault_url(object_type: str, record_id: str) -> str:
    """Construct a Vault deep link."""
    return f"{_VAULT_BASE_URL}/ui/#/{object_type}/{record_id}"


def list_studies(params: dict) -> StudyList:
    """listStudies — list studies with optional filters."""
    conditions = []
    if params.get("status"):
        conditions.append(f"status__v = '{params['status']}'")
    if params.get("phase"):
        conditions.append(f"phase__v = '{params['phase']}'")
    if params.get("therapeutic_area"):
        conditions.append(f"therapeutic_area__v = '{params['therapeutic_area']}'")

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = min(int(params.get("limit", 25)), 100)

    vql = f"SELECT id, name__v, title__v, status__v, phase__v, therapeutic_area__v, sponsor__v FROM study__v{where} LIMIT {limit}"
    rows = vault_query(vql)

    studies = [
        Study(
            study_name=r.get("name__v", ""),
            title=r.get("title__v", ""),
            status=r.get("status__v", ""),
            phase=r.get("phase__v", ""),
            therapeutic_area=r.get("therapeutic_area__v", ""),
            sponsor=r.get("sponsor__v", ""),
            vault_url=_vault_url("study__v", r.get("id", "")),
        )
        for r in rows
    ]
    return StudyList(studies=studies, total_count=len(studies))


def get_study_by_name(params: dict) -> Study:
    """getStudyByName — get a single study by name."""
    name = params["studyName"]
    vql = f"SELECT id, name__v, title__v, status__v, phase__v, therapeutic_area__v, sponsor__v, indication__v, planned_enrollment__v, actual_enrollment__v, start_date__v FROM study__v WHERE name__v = '{name}'"
    rows = vault_query(vql)

    if not rows:
        return Study(study_name=name, title="NOT FOUND")

    r = rows[0]
    return Study(
        study_name=r.get("name__v", name),
        title=r.get("title__v", ""),
        status=r.get("status__v", ""),
        phase=r.get("phase__v", ""),
        therapeutic_area=r.get("therapeutic_area__v", ""),
        sponsor=r.get("sponsor__v", ""),
        indication=r.get("indication__v", ""),
        planned_enrollment=r.get("planned_enrollment__v"),
        actual_enrollment=r.get("actual_enrollment__v"),
        start_date=r.get("start_date__v", ""),
        vault_url=_vault_url("study__v", r.get("id", "")),
    )


def list_sites_for_study(params: dict) -> SiteList:
    """listSitesForStudy — list sites for a given study."""
    study_name = params["studyName"]
    country = params.get("country")
    status = params.get("status")

    conditions = [f"study__vr.name__v = '{study_name}'"]
    if country:
        conditions.append(f"country__v = '{country}'")
    if status:
        conditions.append(f"status__v = '{status}'")

    where = " AND ".join(conditions)
    vql = f"SELECT id, name__v, site_number__v, status__v, country__v, city__v, principal_investigator__v FROM study_site__v WHERE {where} LIMIT 50"
    rows = vault_query(vql)

    sites = [
        Site(
            site_name=r.get("name__v", ""),
            site_number=r.get("site_number__v", ""),
            status=r.get("status__v", ""),
            country=r.get("country__v", ""),
            city=r.get("city__v", ""),
            principal_investigator=r.get("principal_investigator__v", ""),
            vault_url=_vault_url("study_site__v", r.get("id", "")),
        )
        for r in rows
    ]
    return SiteList(sites=sites, study_name=study_name, total_count=len(sites))


def list_milestones_for_study(params: dict) -> MilestoneList:
    """listMilestonesForStudy — list milestones for a study."""
    study_name = params["studyName"]
    vql = f"SELECT id, name__v, milestone_type__v, planned_date__v, actual_date__v, status__v FROM milestone__v WHERE study__vr.name__v = '{study_name}' ORDER BY planned_date__v ASC LIMIT 50"
    rows = vault_query(vql)

    milestones = [
        Milestone(
            milestone_name=r.get("name__v", ""),
            milestone_type=r.get("milestone_type__v", ""),
            planned_date=r.get("planned_date__v", ""),
            actual_date=r.get("actual_date__v", ""),
            status=r.get("status__v", ""),
            vault_url=_vault_url("milestone__v", r.get("id", "")),
        )
        for r in rows
    ]
    return MilestoneList(milestones=milestones, study_name=study_name)


def search_documents(params: dict) -> DocumentList:
    """searchDocuments — search eTMF documents."""
    study_name = params.get("studyName")
    doc_type = params.get("documentType")
    keyword = params.get("keyword")
    limit = min(int(params.get("limit", 20)), 50)

    conditions = []
    if study_name:
        conditions.append(f"study__vr.name__v = '{study_name}'")
    if doc_type:
        conditions.append(f"type__v = '{doc_type}'")
    if keyword:
        conditions.append(f"name__v CONTAINS '{keyword}'")

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    vql = f"SELECT id, name__v, document_number__v, type__v, status__v, major_version_number__v, minor_version_number__v, last_modified_date__v FROM documents{where} LIMIT {limit}"
    rows = vault_query(vql)

    docs = [
        Document(
            document_name=r.get("name__v", ""),
            document_number=r.get("document_number__v", ""),
            document_type=r.get("type__v", ""),
            status=r.get("status__v", ""),
            version=f"{r.get('major_version_number__v', 0)}.{r.get('minor_version_number__v', 0)}",
            last_modified=r.get("last_modified_date__v", ""),
            vault_url=_vault_url("doc", r.get("id", "")),
        )
        for r in rows
    ]
    return DocumentList(documents=docs, total_count=len(docs))


def get_document_metadata(params: dict) -> Document:
    """getDocumentMetadata — get metadata for a specific document."""
    doc_id = params["documentId"]
    vql = f"SELECT id, name__v, document_number__v, type__v, status__v, major_version_number__v, minor_version_number__v, study__vr.name__v, last_modified_date__v FROM documents WHERE id = {doc_id}"
    rows = vault_query(vql)

    if not rows:
        return Document(document_name="NOT FOUND", document_number=str(doc_id))

    r = rows[0]
    return Document(
        document_name=r.get("name__v", ""),
        document_number=r.get("document_number__v", ""),
        document_type=r.get("type__v", ""),
        status=r.get("status__v", ""),
        version=f"{r.get('major_version_number__v', 0)}.{r.get('minor_version_number__v', 0)}",
        study_name=r.get("study__vr.name__v", ""),
        last_modified=r.get("last_modified_date__v", ""),
        vault_url=_vault_url("doc", r.get("id", "")),
    )
