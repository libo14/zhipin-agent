from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from recruitment_agents.checkpointing import build_checkpointer
from recruitment_agents.agents import (
    approval_agent,
    checkpointed_approval_agent,
    communication_agent,
    intent_search_agent,
    resume_screening_agent,
    scheduling_agent,
    technical_evaluation_agent,
)
from recruitment_agents.llm import LLMClient, build_llm
from recruitment_agents.models import RecruitmentState
from recruitment_agents.parsers import ResumeParser
from recruitment_agents.tools.calendar import CalendarScheduler
from recruitment_agents.tools.email import NotificationCenter


def build_workflow(
    llm: LLMClient | None = None,
    parser: ResumeParser | None = None,
    scheduler: CalendarScheduler | None = None,
    notification_center: NotificationCenter | None = None,
    checkpoint_path: str | None = None,
    checkpointer: Any | None = None,
    interrupt_on_approval: bool = True,
) -> Any:
    llm = llm or build_llm()
    parser = parser or ResumeParser()
    scheduler = scheduler or CalendarScheduler()
    notification_center = notification_center or NotificationCenter()

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return LocalRecruitmentWorkflow(llm, parser, scheduler, notification_center)

    graph = StateGraph(RecruitmentState)
    graph.add_node("intent_search_agent", lambda state: intent_search_agent(state, llm))
    graph.add_node("resume_screening_agent", lambda state: resume_screening_agent(state, parser))
    graph.add_node("scheduling_agent", lambda state: scheduling_agent(state, scheduler))
    graph.add_node("technical_evaluation_agent", lambda state: technical_evaluation_agent(state, llm))
    approval_node = checkpointed_approval_agent if interrupt_on_approval else approval_agent
    graph.add_node("approval_agent", approval_node)
    graph.add_node("communication_agent", lambda state: communication_agent(state, notification_center))

    graph.add_edge(START, "intent_search_agent")
    graph.add_edge("intent_search_agent", "resume_screening_agent")
    graph.add_edge("resume_screening_agent", "scheduling_agent")
    graph.add_edge("resume_screening_agent", "technical_evaluation_agent")
    graph.add_edge(["scheduling_agent", "technical_evaluation_agent"], "approval_agent")
    graph.add_edge("approval_agent", "communication_agent")
    graph.add_edge("communication_agent", END)
    if interrupt_on_approval:
        checkpointer = checkpointer or build_checkpointer(checkpoint_path)
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


class LocalRecruitmentWorkflow:
    """Fallback runner with the same invoke API as a compiled LangGraph graph."""

    def __init__(
        self,
        llm: LLMClient,
        parser: ResumeParser,
        scheduler: CalendarScheduler,
        notification_center: NotificationCenter,
    ) -> None:
        self.llm = llm
        self.parser = parser
        self.scheduler = scheduler
        self.notification_center = notification_center

    def invoke(self, initial_state: RecruitmentState, *args: Any, **kwargs: Any) -> RecruitmentState:
        state: RecruitmentState = dict(initial_state)
        self._merge(state, intent_search_agent(state, self.llm))
        self._merge(state, resume_screening_agent(state, self.parser))

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(scheduling_agent, dict(state), self.scheduler),
                executor.submit(technical_evaluation_agent, dict(state), self.llm),
            ]
            for future in futures:
                self._merge(state, future.result())

        self._merge(state, approval_agent(state))
        self._merge(state, communication_agent(state, self.notification_center))
        return state

    def _merge(self, state: RecruitmentState, update: dict[str, Any]) -> None:
        additive_keys = {
            "events",
            "schedule_recommendations",
            "technical_evaluations",
            "notifications",
            "delivery_results",
        }
        for key, value in update.items():
            if key in additive_keys:
                state[key] = state.get(key, []) + value
            else:
                state[key] = value


def draw_mermaid() -> str:
    return """flowchart LR
    START([START]) --> intent[意图搜索 Agent]
    intent --> screen[简历筛选 Agent]
    screen --> schedule[智能排期 Agent]
    screen --> tech[技术面评 Agent]
    schedule --> comm[沟通 Agent]
    tech --> comm
    comm --> END([END])
"""


def draw_mermaid() -> str:
    return """flowchart LR
    START([START]) --> intent[Intent Search Agent]
    intent --> screen[Resume Screening Agent]
    screen --> schedule[Scheduling Agent]
    screen --> tech[Technical Evaluation Agent]
    schedule --> approval[HR Approval Agent]
    tech --> approval
    approval --> comm[Communication Agent]
    comm --> END([END])
"""
