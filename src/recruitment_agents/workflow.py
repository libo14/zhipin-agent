from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from recruitment_agents.checkpointing import build_checkpointer
from recruitment_agents.agents import (
    CommunicationAgent,
    IntentSearchAgent,
    ResumeScreeningAgent,
    SchedulingAgent,
    TechnicalEvaluationAgent,
    approval_agent,
    checkpointed_approval_agent,
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
    intent_agent = IntentSearchAgent(llm)
    screening_agent = ResumeScreeningAgent(parser)
    scheduling_agent_instance = SchedulingAgent(scheduler)
    technical_agent = TechnicalEvaluationAgent(llm)
    communication_agent_instance = CommunicationAgent(notification_center)

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return LocalRecruitmentWorkflow(
            intent_agent=intent_agent,
            screening_agent=screening_agent,
            scheduling_agent=scheduling_agent_instance,
            technical_agent=technical_agent,
            communication_agent=communication_agent_instance,
        )

    graph = StateGraph(RecruitmentState)
    graph.add_node(intent_agent.name, intent_agent.run)
    graph.add_node(screening_agent.name, screening_agent.run)
    graph.add_node(scheduling_agent_instance.name, scheduling_agent_instance.run)
    graph.add_node(technical_agent.name, technical_agent.run)
    approval_node = checkpointed_approval_agent if interrupt_on_approval else approval_agent
    graph.add_node("approval_agent", approval_node)
    graph.add_node(communication_agent_instance.name, communication_agent_instance.run)

    graph.add_edge(START, intent_agent.name)
    graph.add_edge(intent_agent.name, screening_agent.name)
    graph.add_edge(screening_agent.name, scheduling_agent_instance.name)
    graph.add_edge(screening_agent.name, technical_agent.name)
    graph.add_edge([scheduling_agent_instance.name, technical_agent.name], "approval_agent")
    graph.add_edge("approval_agent", communication_agent_instance.name)
    graph.add_edge(communication_agent_instance.name, END)
    if interrupt_on_approval:
        checkpointer = checkpointer or build_checkpointer(checkpoint_path)
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


class LocalRecruitmentWorkflow:
    """Fallback runner with the same invoke API as a compiled LangGraph graph."""

    def __init__(
        self,
        intent_agent: IntentSearchAgent,
        screening_agent: ResumeScreeningAgent,
        scheduling_agent: SchedulingAgent,
        technical_agent: TechnicalEvaluationAgent,
        communication_agent: CommunicationAgent,
    ) -> None:
        self.intent_agent = intent_agent
        self.screening_agent = screening_agent
        self.scheduling_agent = scheduling_agent
        self.technical_agent = technical_agent
        self.communication_agent = communication_agent

    def invoke(self, initial_state: RecruitmentState, *args: Any, **kwargs: Any) -> RecruitmentState:
        state: RecruitmentState = dict(initial_state)
        self._merge(state, self.intent_agent.run(state))
        self._merge(state, self.screening_agent.run(state))

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.scheduling_agent.run, dict(state)),
                executor.submit(self.technical_agent.run, dict(state)),
            ]
            for future in futures:
                self._merge(state, future.result())

        self._merge(state, approval_agent(state))
        self._merge(state, self.communication_agent.run(state))
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
    START([START]) --> intent[Intent Search Agent]
    intent --> screen[Resume Screening Agent]
    screen --> schedule[Scheduling Agent]
    screen --> tech[Technical Evaluation Agent]
    schedule --> approval[HR Approval Agent]
    tech --> approval
    approval --> comm[Communication Agent]
    comm --> END([END])
"""
