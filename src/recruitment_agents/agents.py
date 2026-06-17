from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

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


@dataclass(frozen=True)
class AgentMetadata:
    name: str
    role: str
    description: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReActStep:
    reason: str
    action: str
    observation: str
    tool: str


class RecruitmentAgent(Protocol):
    metadata: AgentMetadata

    @property
    def name(self) -> str:
        ...

    @property
    def role(self) -> str:
        ...

    @property
    def description(self) -> str:
        ...

    @property
    def tools(self) -> tuple[str, ...]:
        ...

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        ...


class AgentBase:
    metadata: AgentMetadata

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def role(self) -> str:
        return self.metadata.role

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def tools(self) -> tuple[str, ...]:
        return self.metadata.tools

    def react_event(self, step: ReActStep, summary: str, level: str = "info") -> WorkflowEvent:
        return WorkflowEvent(
            node=self.name,
            message=(
                f"ReAct | Reason: {step.reason} | Action: {step.action} | "
                f"Tool: {step.tool} | Observation: {step.observation}。{summary}"
            ),
            level=level,
        )


class IntentSearchAgent(AgentBase):
    metadata = AgentMetadata(
        name="intent_search_agent",
        role="JD intent analyst",
        description="Parse the job description into structured hiring intent.",
        tools=("LLMClient", "rule_based_jd_parser"),
    )

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        job_description = state.get("job_description", "")
        intent = extract_job_intent(job_description)
        summary = message_text(
            self.llm.invoke(
                "请根据岗位描述输出招聘意图摘要，重点包含岗位、技能、经验、学历和地点：\n"
                f"{job_description[:3000]}"
            )
        )
        step = ReActStep(
            reason="需要先把非结构化 JD 转换成后续筛选可消费的岗位意图。",
            action="调用规则 JD 解析器提取硬性字段，并调用 LLMClient 生成意图摘要。",
            observation=f"识别岗位 {intent.title}，提取 {len(intent.required_skills)} 个核心技能。",
            tool="rule_based_jd_parser, LLMClient",
        )
        return {
            "intent": intent,
            "events": [
                self.react_event(
                    step,
                    f"识别岗位 {intent.title}，核心技能 {', '.join(intent.required_skills)}。{summary[:80]}",
                )
            ],
        }


class ResumeScreeningAgent(AgentBase):
    metadata = AgentMetadata(
        name="resume_screening_agent",
        role="Resume screening specialist",
        description="Parse resumes and score candidates against the structured job intent.",
        tools=("ResumeParser", "score_candidate"),
    )

    def __init__(self, parser: ResumeParser) -> None:
        self.parser = parser

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        intent = state["intent"]
        threshold = float(state.get("threshold", 70))
        profiles = self.parser.parse_many(state.get("resume_paths", []))
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
        step = ReActStep(
            reason="需要把候选人简历转为结构化画像，并与岗位意图进行可解释匹配。",
            action="调用 ResumeParser 读取简历，再调用 score_candidate 完成加权评分和排序。",
            observation=f"解析 {len(profiles)} 份简历，输出 {len(selected or matches[:3])} 个候选匹配结果。",
            tool="ResumeParser, score_candidate",
        )

        return {
            "candidate_profiles": profiles,
            "candidate_matches": selected or matches[:3],
            "events": [
                self.react_event(
                    step,
                    f"解析 {len(profiles)} 份简历，按技能60%+经验30%+学历10%完成加权评分。",
                )
            ],
        }


class SchedulingAgent(AgentBase):
    metadata = AgentMetadata(
        name="scheduling_agent",
        role="Interview scheduling coordinator",
        description="Recommend interview slots for shortlisted candidates.",
        tools=("CalendarScheduler",),
    )

    def __init__(self, scheduler: CalendarScheduler) -> None:
        self.scheduler = scheduler

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        self.scheduler.timezone = state.get("timezone", self.scheduler.timezone)
        recommendations = self.scheduler.recommend(state.get("candidate_matches", []))
        step = ReActStep(
            reason="候选人已完成筛选，需要为可推进候选人生成可执行的面试时间建议。",
            action="调用 CalendarScheduler 基于候选人列表、时区和冲突窗口推荐面试时段。",
            observation=f"生成 {len(recommendations)} 组候选人排期建议。",
            tool="CalendarScheduler",
        )
        return {
            "schedule_recommendations": recommendations,
            "events": [
                self.react_event(
                    step,
                    f"完成 {len(recommendations)} 名候选人的跨时区面试时段推荐。",
                )
            ],
        }


class TechnicalEvaluationAgent(AgentBase):
    metadata = AgentMetadata(
        name="technical_evaluation_agent",
        role="Technical interview designer",
        description="Generate interview focus areas, questions, risk flags, and interviewer briefs.",
        tools=("LLMClient", "technical_report_builder"),
    )

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        intent = state["intent"]
        matches = state.get("candidate_matches", [])
        reports = [
            build_technical_report(match, intent, self.llm)
            for match in matches
            if match.recommendation != "reject"
        ]
        step = ReActStep(
            reason="筛选结果需要转化成面试官可使用的技术评估重点。",
            action="基于匹配分、技能缺口和岗位意图生成技术面试问题与 brief。",
            observation=f"为 {len(reports)} 名非拒绝候选人生成技术面评。",
            tool="technical_report_builder, LLMClient",
        )
        return {
            "technical_evaluations": reports,
            "events": [
                self.react_event(
                    step,
                    f"为 {len(reports)} 名候选人生成技术面评问题与风险提示。",
                )
            ],
        }


class CommunicationAgent(AgentBase):
    metadata = AgentMetadata(
        name="communication_agent",
        role="Recruiting communication operator",
        description="Build notifications and deliver drafts or approved messages through configured channels.",
        tools=("NotificationCenter",),
    )

    def __init__(self, notification_center: NotificationCenter) -> None:
        self.notification_center = notification_center

    def run(self, state: RecruitmentState) -> dict[str, Any]:
        notifications = self.notification_center.build_notifications(
            matches=state.get("candidate_matches", []),
            schedules=state.get("schedule_recommendations", []),
            technical_reports=state.get("technical_evaluations", []),
        )
        delivery_results = self.notification_center.deliver_notifications(
            notifications=notifications,
            outbox_dir=state.get("outbox_dir"),
            approval_decision=state.get("approval_decision"),
        )
        step = ReActStep(
            reason="流程已完成评估和审批，需要把状态转化为候选人、面试官和 HR 可接收的通知。",
            action="调用 NotificationCenter 生成通知，并根据审批状态投递到配置通道。",
            observation=f"生成 {len(notifications)} 封通知，记录 {len(delivery_results)} 条投递结果。",
            tool="NotificationCenter",
        )

        return {
            "notifications": notifications,
            "delivery_results": delivery_results,
            "events": [
                self.react_event(
                    step,
                    f"监听流程状态并生成 {len(notifications)} 封状态流转邮件，完成 {len(delivery_results)} 条投递记录。",
                )
            ],
        }


def intent_search_agent(state: RecruitmentState, llm: LLMClient) -> dict[str, Any]:
    return IntentSearchAgent(llm).run(state)


def resume_screening_agent(state: RecruitmentState, parser: ResumeParser) -> dict[str, Any]:
    return ResumeScreeningAgent(parser).run(state)


def scheduling_agent(state: RecruitmentState, scheduler: CalendarScheduler) -> dict[str, Any]:
    return SchedulingAgent(scheduler).run(state)


def technical_evaluation_agent(state: RecruitmentState, llm: LLMClient) -> dict[str, Any]:
    return TechnicalEvaluationAgent(llm).run(state)


def communication_agent(state: RecruitmentState, notification_center: NotificationCenter) -> dict[str, Any]:
    return CommunicationAgent(notification_center).run(state)


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
