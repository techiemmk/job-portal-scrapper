from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Literal
from datetime import datetime

class JobMetadata(BaseModel):
    job_id: str
    job_title: str
    organization_name: str
    job_department: Optional[str] = ""
    job_link: str
    posted_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

class JobLogistics(BaseModel):
    job_locations: List[str] = []
    work_mode: Literal["remote", "hybrid", "onsite"] = "onsite"
    travel_requirement: Optional[str] = "Not specified"
    job_type: Optional[str] = "Full-time"

class JobRoleDetails(BaseModel):
    job_description: Optional[str] = ""
    job_responsibilities: Optional[str] = ""
    minimum_qualifications: Optional[str] = ""
    preferred_qualifications: Optional[str] = ""
    language_requirements: List[str] = ["English"]
    job_details_metadata: Optional[str] = ""

class JobCompensation(BaseModel):
    salary_range: Optional[str] = ""
    compensation_details: Optional[str] = ""
    benefits_and_perks: Optional[str] = ""

class JobLegalCompany(BaseModel):
    about_company: Optional[str] = ""
    equal_employment_opportunity: Optional[str] = ""
    additional_links: List[str] = []

class RAGJobPosting(BaseModel):
    metadata: JobMetadata
    logistics: JobLogistics
    role_details: JobRoleDetails
    compensation: JobCompensation
    legal_and_company: JobLegalCompany

class ScraperRunBatch(BaseModel):
    startTime: str
    endTime: str
    status: str = "completed"
    companyName: str
    websiteName: str
    data: List[RAGJobPosting]
