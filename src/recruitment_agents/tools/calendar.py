from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from recruitment_agents.models import CandidateMatch, InterviewRecommendation, InterviewSlot


class CalendarScheduler:
    """Calendar adapter.

    The demo uses deterministic mock availability. Replace `_busy_windows` and
    `recommend` internals with Google Calendar API calls in production.
    """

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = timezone

    def recommend(
        self,
        matches: list[CandidateMatch],
        duration_minutes: int = 60,
        limit_per_candidate: int = 2,
    ) -> list[InterviewRecommendation]:
        recommendations = []
        for match in matches:
            if match.recommendation == "reject":
                continue
            slots = self._candidate_slots(duration_minutes, limit_per_candidate)
            recommendations.append(
                InterviewRecommendation(
                    candidate_name=match.candidate.name,
                    candidate_email=match.candidate.email,
                    slots=slots,
                    reason="避开 HR 与候选人已占用时间后，优先选择工作日 10:00/14:00/16:00 的高响应时段。",
                )
            )
        return recommendations

    def _candidate_slots(self, duration_minutes: int, limit: int) -> list[InterviewSlot]:
        tz = load_timezone(self.timezone)
        today = datetime.now(tz).date()
        starts: list[datetime] = []
        for offset in range(1, 8):
            day = today + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            for slot_time in [time(10, 0), time(14, 0), time(16, 0)]:
                candidate = datetime.combine(day, slot_time, tzinfo=tz)
                if not self._has_conflict(candidate, duration_minutes):
                    starts.append(candidate)
                if len(starts) >= limit:
                    break
            if len(starts) >= limit:
                break

        return [
            InterviewSlot(
                starts_at=start,
                ends_at=start + timedelta(minutes=duration_minutes),
                timezone=self.timezone,
            )
            for start in starts
        ]

    def _has_conflict(self, starts_at: datetime, duration_minutes: int) -> bool:
        busy_windows = self._busy_windows(starts_at.tzinfo)
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        return any(starts_at < busy_end and ends_at > busy_start for busy_start, busy_end in busy_windows)

    def _busy_windows(self, tzinfo) -> list[tuple[datetime, datetime]]:
        today = datetime.now(tzinfo).date()
        tomorrow = today + timedelta(days=1)
        return [
            (
                datetime.combine(tomorrow, time(14, 0), tzinfo=tzinfo),
                datetime.combine(tomorrow, time(15, 0), tzinfo=tzinfo),
            )
        ]


def load_timezone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        fixed_offsets = {
            "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
            "UTC": timezone.utc,
        }
        return fixed_offsets.get(name, timezone.utc)
