from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class JobIntent(BaseModel):
    title: str = Field(description="Target role title.")
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    min_years_experience: float = 0
    education_requirement: str = "不限"
    location: str = "Remote"
    seniority: str = "Mid"
    keywords: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    years_experience: float = 0
    education: str = "未知"
    latest_company: Optional[str] = None
    source_path: str
    raw_text: str = Field(default="", exclude=True)


class ScoreBreakdown(BaseModel):
    skill_score: float = Field(ge=0, le=100)
    experience_score: float = Field(ge=0, le=100)
    education_score: float = Field(ge=0, le=100)
    weighted_total: float = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class CandidateMatch(BaseModel):
    candidate: CandidateProfile
    score: ScoreBreakdown
    recommendation: Literal["strong_match", "match", "backup", "reject"]
    rationale: str


class InterviewSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str


class InterviewRecommendation(BaseModel):
    candidate_name: str
    candidate_email: Optional[str] = None
    slots: list[InterviewSlot] = Field(default_factory=list)
    reason: str


class TechnicalEvaluation(BaseModel):
    candidate_name: str
    focus_areas: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    interviewer_brief: str


class EmailNotification(BaseModel):
    category: Literal[
        "resume_received",
        "shortlisted",
        "interview_invite",
        "technical_brief",
        "rejection",
        "hr_digest",
    ]
    recipient: str
    subject: str
    body: str


class ApprovalDecision(BaseModel):
    status: Literal["pending", "approved", "rejected"] = "pending"
    approved_by: Optional[str] = None
    notes: str = ""
    approved_at: Optional[datetime] = None


class DeliveryResult(BaseModel):
    channel: Literal["json", "smtp", "sendgrid", "feishu"]
    recipient: str
    category: str
    status: Literal["drafted", "sent", "skipped", "failed"]
    detail: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowEvent(BaseModel):
    node: str
    message: str
    level: Literal["info", "warning", "error"] = "info"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecruitmentState(TypedDict, total=False):
    job_description: str
    resume_paths: list[str]
    threshold: float
    timezone: str
    outbox_dir: str
    approval_status: Literal["pending", "approved", "rejected"]
    approval_file: str
    approved_by: str
    approval_notes: str
    intent: JobIntent
    candidate_profiles: list[CandidateProfile]
    candidate_matches: list[CandidateMatch]
    schedule_recommendations: Annotated[list[InterviewRecommendation], operator.add]
    technical_evaluations: Annotated[list[TechnicalEvaluation], operator.add]
    approval_decision: ApprovalDecision
    notifications: Annotated[list[EmailNotification], operator.add]
    delivery_results: Annotated[list[DeliveryResult], operator.add]
    events: Annotated[list[WorkflowEvent], operator.add]
