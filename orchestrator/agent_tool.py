"""원격 A2A 에이전트 카드를 ReAct가 호출 가능한 LLM tool로 변환한다."""
from collections.abc import Callable

from langchain_core.tools import StructuredTool

from a2a.types import AgentCard

from orchestrator.client import call_agent
from orchestrator.events import ProgressEvent


def build_agent_tool(
    http,
    name: str,
    card: AgentCard,
    call_agent_fn=call_agent,
    emit: Callable[[ProgressEvent], None] | None = None,
) -> StructuredTool:
    """원격 A2A 에이전트 하나를 ReAct가 호출 가능한 단일 인자 tool로 감싸고 서브 진행을 emit로 방출한다."""
    def on_sub_event(metadata: dict) -> None:
        if emit is None:
            return
        emit(sub_progress_event(name, metadata))

    async def call(input: str) -> str:
        try:
            return await call_agent_fn(http, card, input, on_event=on_sub_event)
        # 루프 무중단 보장: 예외를 그래프로 전파하지 않고 LLM이 관찰할 텍스트로 흡수한다.
        except Exception as error:  # noqa: BLE001
            return f"[error calling {name}: {error}]"
    return StructuredTool.from_function(
        coroutine=call,
        name=name,
        description=tool_description(card),
    )


def tool_description(card: AgentCard) -> str:
    """카드의 description과 skill 이름을 LLM tool description 문자열로 합친다."""
    skills = ", ".join(skill.name for skill in card.skills)
    return f"{card.description} (skills: {skills})"


def sub_progress_event(agent_name: str, metadata: dict) -> ProgressEvent:
    """서브 에이전트 진행 metadata를 path가 부여된 ProgressEvent로 변환한다."""
    return ProgressEvent(
        type=metadata["kind"],
        agent=metadata.get("agent"),
        input=metadata.get("input"),
        output=metadata.get("output"),
        path=[agent_name],
    )
