"""원격 A2A 에이전트 카드를 ReAct가 호출 가능한 LLM tool로 변환한다."""
from langchain_core.tools import StructuredTool

from a2a.types import AgentCard

from orchestrator.client import call_agent


def build_agent_tool(http, name: str, card: AgentCard, call_agent_fn=call_agent) -> StructuredTool:
    """원격 A2A 에이전트 하나를 ReAct가 호출 가능한 단일-인자 tool로 감싼다."""
    async def call(input: str) -> str:
        try:
            return await call_agent_fn(http, card, input)
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
