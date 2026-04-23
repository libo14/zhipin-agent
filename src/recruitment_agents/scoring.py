from __future__ import annotations

from recruitment_agents.models import CandidateMatch, CandidateProfile, JobIntent, ScoreBreakdown


EDUCATION_RANK = {
    "未知": 0,
    "不限": 0,
    "大专": 1,
    "本科": 2,
    "硕士": 3,
    "博士": 4,
}


def normalize_skill(skill: str) -> str:
    return skill.strip().lower().replace(".", "").replace("-", "")


def score_candidate(
    candidate: CandidateProfile,
    intent: JobIntent,
    skill_weight: float = 0.6,
    experience_weight: float = 0.3,
    education_weight: float = 0.1,
) -> CandidateMatch:
    required = [normalize_skill(skill) for skill in intent.required_skills]
    candidate_skills = {normalize_skill(skill): skill for skill in candidate.skills}

    matched = []
    missing = []
    for raw, normalized in zip(intent.required_skills, required):
        is_match = normalized in candidate_skills or any(
            normalized in skill or skill in normalized for skill in candidate_skills
        )
        if is_match:
            matched.append(raw)
        else:
            missing.append(raw)

    skill_score = 100.0 if not required else round(len(matched) / len(required) * 100, 2)

    if intent.min_years_experience <= 0:
        experience_score = 100.0
    else:
        min_years = max(intent.min_years_experience, 0.1)
        experience_score = min(candidate.years_experience / min_years * 100, 100)

    required_rank = education_rank(intent.education_requirement)
    candidate_rank = education_rank(candidate.education)
    if required_rank == 0:
        education_score = 100.0
    else:
        education_score = min(candidate_rank / required_rank * 100, 100)

    weighted_total = round(
        skill_score * skill_weight
        + experience_score * experience_weight
        + education_score * education_weight,
        2,
    )

    if weighted_total >= 85:
        recommendation = "strong_match"
    elif weighted_total >= 70:
        recommendation = "match"
    elif weighted_total >= 55:
        recommendation = "backup"
    else:
        recommendation = "reject"

    rationale = (
        f"技能匹配 {skill_score:.1f}%，经验匹配 {experience_score:.1f}%，"
        f"学历匹配 {education_score:.1f}%，综合得分 {weighted_total:.1f}。"
    )

    return CandidateMatch(
        candidate=candidate,
        score=ScoreBreakdown(
            skill_score=round(skill_score, 2),
            experience_score=round(experience_score, 2),
            education_score=round(education_score, 2),
            weighted_total=weighted_total,
            matched_skills=matched,
            missing_skills=missing,
        ),
        recommendation=recommendation,
        rationale=rationale,
    )


def education_rank(value: str) -> int:
    text = value.lower()
    if "博士" in text or "phd" in text:
        return EDUCATION_RANK["博士"]
    if "硕士" in text or "master" in text:
        return EDUCATION_RANK["硕士"]
    if "本科" in text or "bachelor" in text:
        return EDUCATION_RANK["本科"]
    if "大专" in text or "college" in text:
        return EDUCATION_RANK["大专"]
    if "不限" in text:
        return EDUCATION_RANK["不限"]
    return EDUCATION_RANK["未知"]
