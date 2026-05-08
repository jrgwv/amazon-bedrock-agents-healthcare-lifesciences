"""Pydantic v2 response models for Vault clinical data."""

from pydantic import BaseModel, Field


class Study(BaseModel):
    study_name: str = Field(description="Study identifier (e.g., BMS-986365-001)")
    title: str = Field(default="", description="Full study title")
    status: str = Field(default="", description="Study status")
    phase: str = Field(default="", description="Study phase")
    therapeutic_area: str = Field(default="", description="Therapeutic area")
    sponsor: str = Field(default="", description="Sponsor organization")
    indication: str = Field(default="", description="Primary indication")
    planned_enrollment: int | None = Field(default=None, description="Target enrollment count")
    actual_enrollment: int | None = Field(default=None, description="Current enrollment count")
    start_date: str = Field(default="", description="Study start date")
    vault_url: str = Field(default="", description="Deep link to record in Vault")


class StudyList(BaseModel):
    studies: list[Study] = Field(default_factory=list)
    total_count: int = Field(default=0)


class Site(BaseModel):
    site_name: str = Field(description="Site name")
    site_number: str = Field(default="", description="Site number")
    status: str = Field(default="", description="Site status")
    country: str = Field(default="", description="Country")
    city: str = Field(default="", description="City")
    principal_investigator: str = Field(default="", description="PI name")
    planned_enrollment: int | None = Field(default=None)
    actual_enrollment: int | None = Field(default=None)
    vault_url: str = Field(default="")


class SiteList(BaseModel):
    sites: list[Site] = Field(default_factory=list)
    study_name: str = Field(default="")
    total_count: int = Field(default=0)


class Milestone(BaseModel):
    milestone_name: str = Field(description="Milestone name")
    milestone_type: str = Field(default="", description="Type (e.g., regulatory, enrollment)")
    planned_date: str = Field(default="", description="Planned date")
    actual_date: str = Field(default="", description="Actual date (if completed)")
    status: str = Field(default="", description="Status")
    vault_url: str = Field(default="")


class MilestoneList(BaseModel):
    milestones: list[Milestone] = Field(default_factory=list)
    study_name: str = Field(default="")


class Document(BaseModel):
    document_name: str = Field(description="Document name")
    document_number: str = Field(default="")
    document_type: str = Field(default="", description="Document type/subtype")
    status: str = Field(default="", description="Document status")
    version: str = Field(default="", description="Major.minor version")
    study_name: str = Field(default="")
    last_modified: str = Field(default="")
    vault_url: str = Field(default="")


class DocumentList(BaseModel):
    documents: list[Document] = Field(default_factory=list)
    total_count: int = Field(default=0)
