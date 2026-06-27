"""에이전트 카드를 근거로 LLM이 호출 계획을 산출해 동적으로 라우팅한다."""
import json
import re
from typing import TypedDict

from a2a.types import AgentCard

from orchestrator.llm import message_content_to_text

PREVIOUS_OUTPUT_PLACEHOLDER = "{PREVIOUS_OUTPUT}"

PLANNER_SYSTEM_PROMPT = (
    "You are an orchestrator. Given a user task and a catalog of agents, "
    "produce a JSON array of calls to fulfill the task. Each element is "
    '{"agent": <agent name>, "input": <text to send>}. Call agents in order; '
    f'use the literal string "{PREVIOUS_OUTPUT_PLACEHOLDER}" inside an input to '
    "insert the previous call's output. Respond with ONLY the JSON array."
)


class PlannedCall(TypedDict):
    agent: str
    input: str


def cards_to_catalog(cards: dict[str, AgentCard]) -> str:
    """에이전트 카드를 LLM 프롬프트용 사람이 읽기 좋은 카탈로그로 변환한다."""
    lines = []
    for name, card in cards.items():
        skills = ", ".join(skill.name for skill in card.skills)
        lines.append(f"- {name}: {card.description} (skills: {skills})")
    return "\n".join(lines)


def _parse_plan(raw: str) -> list[PlannedCall]:
    """원본 LLM 응답 텍스트에서 PlannedCall 딕셔너리 목록을 추출한다."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    payload = match.group(0) if match else raw
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    plan: list[PlannedCall] = []
    for item in parsed:
        if isinstance(item, dict) and "agent" in item and "input" in item:
            plan.append({"agent": str(item["agent"]), "input": str(item["input"])})
    return plan


async def plan_calls(
    task: str,
    cards: dict[str, AgentCard],
    model=None,
    max_calls: int = 5,
) -> list[PlannedCall]:
    """주어진 Task에 대해 LLM으로 순서가 있는 에이전트 호출 목록을 산출한다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    catalog = cards_to_catalog(cards)
    response = await model.ainvoke(
        [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\nAgents:\n{catalog}"},
        ]
    )
    plan = _parse_plan(message_content_to_text(response))
    resolved_calls = [call for call in plan if call["agent"] in cards]
    return resolved_calls[:max_calls]
