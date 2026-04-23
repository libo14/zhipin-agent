from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from recruitment_agents.llm import LLMClient, message_text
from recruitment_agents.models import (
    ApprovalDecision,
    CandidateMatch,
    JobIntent,
    RecruitmentState,
    TechnicalEvaluation,
    WorkflowEvent,
)
from recruitment_agents.parsers import ResumeParser, SKILL_KEYWORDS
from recruitment_agents.scoring import score_candidate
from recruitment_agents.tools.calendar import CalendarScheduler
from recruitment_agents.tools.email import NotificationCenter


def intent_search_agent(state: RecruitmentState, llm: LLMClient) -> dict[str, Any]:
    job_description = state.get("job_description", "")
    intent = extract_job_intent(job_description)
    summary = message_text(
        llm.invoke(
            "请根据岗位描述输出招聘意图摘要，重点包含岗位、技能、经验、学历和地点：\n"
            f"{job_description[:3000]}"
        )
    )
    return {
        "intent": intent,
        "events": [
            WorkflowEvent(
                node="intent_search_agent",
                message=f"识别岗位 {intent.title}，核心技能 {', '.join(intent.required_skills)}。{summary[:80]}",
            )
        ],
    }


def resume_screening_agent(state: RecruitmentState, parser: ResumeParser) -> dict[str, Any]:
    intent = state["intent"]
    threshold = float(state.get("threshold", 70))
    profiles = parser.parse_many(state.get("resume_paths", []))
    matches = sorted(
        [score_candidate(profile, intent) for profile in profiles],
        key=lambda item: item.score.weighted_total,
        reverse=True,
    )
    selected = [
        match
        for match in matches
        if match.score.weighted_total >= threshold or match.recommendation in {"strong_match", "match"}
    ]

    return {
        "candidate_profiles": profiles,
        "candidate_matches": selected or matches[:3],
        "events": [
            WorkflowEvent(
                node="resume_screening_agent",
                message=f"解析 {len(profiles)} 份简历，按技能60%+经验30%+学历10%完成加权评分。",
            )
        ],
    }


def scheduling_agent(state: RecruitmentState, scheduler: CalendarScheduler) -> dict[str, Any]:
    scheduler.timezone = state.get("timezone", scheduler.timezone)
    recommendations = scheduler.recommend(state.get("candidate_matches", []))
    return {
        "schedule_recommendations": recommendations,
        "events": [
            WorkflowEvent(
                node="scheduling_agent",
                message=f"完成 {len(recommendations)} 名候选人的跨时区面试时段推荐。",
            )
        ],
    }


def technical_evaluation_agent(state: RecruitmentState, llm: LLMClient) -> dict[str, Any]:
    intent = state["intent"]
    matches = state.get("candidate_matches", [])
    reports = [build_technical_report(match, intent, llm) for match in matches if match.recommendation != "reject"]
    return {
        "technical_evaluations": reports,
        "events": [
            WorkflowEvent(
                node="technical_evaluation_agent",
                message=f"为 {len(reports)} 名候选人生成技术面评问题与风险提示。",
            )
        ],
    }


def approval_agent(state: RecruitmentState) -> dict[str, Any]:
    decision = resolve_approval_decision(state)
    return approval_update(decision)


def checkpointed_approval_agent(state: RecruitmentState) -> dict[str, Any]:
    decision = resolve_approval_decision(state)
    if decision.status != "pending":
        return approval_update(decision)

    try:
        from langgraph.types import interrupt
    except ImportError:
        return approval_update(decision)

    resume_value = interrupt(
        {
            "type": "hr_approval_required",
            "message": "Review candidate-facing notifications before external delivery.",
            "candidate_count": len(state.get("candidate_matches", [])),
            "notification_count": len(state.get("notifications", [])),
            "allowed_statuses": ["approved", "rejected"],
        }
    )
    return approval_update(approval_decision_from_resume(resume_value))


def approval_update(decision: ApprovalDecision) -> dict[str, Any]:
    level = "info" if decision.status == "approved" else "warning"
    return {
        "approval_decision": decision,
        "events": [
            WorkflowEvent(
                node="approval_agent",
                message=f"HR approval status is {decision.status}. Candidate-facing sends are gated until approval.",
                level=level,
            )
        ],
    }


def approval_decision_from_resume(value: Any) -> ApprovalDecision:
    if isinstance(value, ApprovalDecision):
        return value
    if isinstance(value, dict):
        status = normalize_approval_status(value.get("status") or value.get("approved"))
        return ApprovalDecision(
            status=status,
            approved_by=value.get("approved_by") or value.get("approver"),
            notes=value.get("notes", ""),
            approved_at=datetime.utcnow() if status == "approved" else None,
        )
    status = normalize_approval_status(value)
    return ApprovalDecision(status=status, approved_at=datetime.utcnow() if status == "approved" else None)


def communication_agent(state: RecruitmentState, notification_center: NotificationCenter) -> dict[str, Any]:
    notifications = notification_center.build_notifications(
        matches=state.get("candidate_matches", []),
        schedules=state.get("schedule_recommendations", []),
        technical_reports=state.get("technical_evaluations", []),
    )
    delivery_results = notification_center.deliver_notifications(
        notifications=notifications,
        outbox_dir=state.get("outbox_dir"),
        approval_decision=state.get("approval_decision"),
    )

    return {
        "notifications": notifications,
        "delivery_results": delivery_results,
        "events": [
            WorkflowEvent(
                node="communication_agent",
                message=f"监听流程状态并生成 {len(notifications)} 封状态流转邮件，完成 {len(delivery_results)} 条投递记录。",
            )
        ],
    }


def resolve_approval_decision(state: RecruitmentState) -> ApprovalDecision:
    approval_file = state.get("approval_file") or os.getenv("HR_APPROVAL_FILE")
    if approval_file:
        path = Path(approval_file)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            status = payload.get("status") or ("approved" if payload.get("approved") else "pending")
            normalized = normalize_approval_status(status)
            return ApprovalDecision(
                status=normalized,
                approved_by=payload.get("approved_by") or payload.get("approver"),
                notes=payload.get("notes", ""),
                approved_at=datetime.utcnow() if normalized == "approved" else None,
            )

    status = (
        state.get("approval_status")
        or os.getenv("HR_APPROVAL_STATUS")
        or ("approved" if os.getenv("HR_APPROVAL_MODE", "").lower() == "auto" else "pending")
    )
    normalized = normalize_approval_status(status)
    return ApprovalDecision(
        status=normalized,
        approved_by=state.get("approved_by") or os.getenv("HR_APPROVED_BY"),
        notes=state.get("approval_notes") or os.getenv("HR_APPROVAL_NOTES", ""),
        approved_at=datetime.utcnow() if normalized == "approved" else None,
    )


def normalize_approval_status(value: Any) -> str:
    status = str(value).strip().lower()
    if status in {"approved", "approve", "yes", "true", "1"}:
        return "approved"
    if status in {"rejected", "reject", "no", "false", "0"}:
        return "rejected"
    return "pending"


def extract_job_intent(job_description: str) -> JobIntent:
    text = job_description.strip()
    lowered = text.lower()
    title = extract_title(text)
    required_skills = []
    nice_to_have = []

    bonus_zone = extract_bonus_zone(text)
    for skill in SKILL_KEYWORDS:
        if skill.lower() in lowered:
            if skill.lower() in bonus_zone:
                nice_to_have.append(skill)
            else:
                required_skills.append(skill)

    if not required_skills:
        required_skills = ["python", "langchain", "langgraph"]

    years = extract_years_requirement(text)
    education = extract_education_requirement(text)
    location = extract_location(text)
    seniority = "Senior" if years >= 5 else "Mid" if years >= 2 else "Junior"

    return JobIntent(
        title=title,
        required_skills=required_skills,
        nice_to_have_skills=nice_to_have,
        min_years_experience=years,
        education_requirement=education,
        location=location,
        seniority=seniority,
        keywords=required_skills + nice_to_have,
    )


def build_technical_report(match: CandidateMatch, intent: JobIntent, llm: LLMClient) -> TechnicalEvaluation:
    missing = match.score.missing_skills
    matched = match.score.matched_skills
    focus_areas = missing[:3] or matched[:3] or intent.required_skills[:3]
    questions = [
        f"请结合真实项目说明你如何使用 {skill} 解决复杂问题。"
        for skill in focus_areas
    ]
    questions.append("请设计一个招聘场景下的 Agent 状态机，并说明失败重试与人工介入策略。")
    questions.append("如果简历解析结果不稳定，你会如何评估并提升抽取准确率？")

    risk_flags = []
    if match.score.experience_score < 80:
        risk_flags.append("项目年限低于岗位要求，需要追问独立负责范围。")
    if missing:
        risk_flags.append(f"关键技能缺口：{', '.join(missing)}。")
    if not risk_flags:
        risk_flags.append("无明显硬性风险，建议重点验证系统设计深度。")

    prompt = (
        f"候选人 {match.candidate.name} 应聘 {intent.title}，"
        f"匹配技能 {matched}，缺口 {missing}，请生成一句面试官 brief。"
    )
    llm_brief = message_text(llm.invoke(prompt))
    interviewer_brief = (
        f"{match.candidate.name} 综合得分 {match.score.weighted_total}。"
        f"建议关注：{'; '.join(focus_areas)}。\n{llm_brief}"
    )
    return TechnicalEvaluation(
        candidate_name=match.candidate.name,
        focus_areas=focus_areas,
        questions=questions,
        risk_flags=risk_flags,
        interviewer_brief=interviewer_brief,
    )


def extract_title(text: str) -> str:
    for pattern in [
        r"(?:岗位|职位|Role|Title)[:：]\s*([^\n\r]{2,50})",
        r"招聘\s*([^\n\r，。]{2,30})",
    ]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:40] or "AI Agent Engineer"


def extract_bonus_zone(text: str) -> str:
    match = re.search(r"(?:加分|优先|nice to have|preferred)[:：]?\s*([\s\S]{0,500})", text, flags=re.I)
    return match.group(1).lower() if match else ""


def extract_years_requirement(text: str) -> float:
    if "不限" in text and ("经验" in text or "年限" in text):
        return 0.0

    no_experience_patterns = [
        r"不限经验",
        r"经验不限",
        r"无需经验",
        r"无经验要求",
        r"不要求经验",
        r"应届",
        r"校招",
        r"no\s+experience",
        r"entry\s*level",
    ]
    if any(re.search(pattern, text, flags=re.I) for pattern in no_experience_patterns):
        return 0.0

    match = re.search(r"(\d+(?:\.\d+)?)\+?\s*(?:年|years?)", text, flags=re.I)
    return float(match.group(1)) if match else 3.0


def extract_education_requirement(text: str) -> str:
    for keyword in ["博士", "PhD", "硕士", "Master", "本科", "Bachelor", "大专", "College"]:
        if keyword.lower() in text.lower():
            return keyword
    if "学历不限" in text or "不限学历" in text:
        return "不限"
    return "本科"


def extract_location(text: str) -> str:
    match = re.search(r"(?:地点|Location)[:：]\s*([^\n\r]{2,30})", text, flags=re.I)
    return match.group(1).strip() if match else "Remote"
