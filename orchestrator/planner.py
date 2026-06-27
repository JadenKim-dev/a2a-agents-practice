"""에이전트 카드를 근거로 LLM이 호출 계획을 산출하는 동적 라우팅 책임."""
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
    """Responsible for converting agent cards into a human-readable catalog for LLM prompts."""
    lines = []
    for name, card in cards.items():
        skills = ", ".join(skill.name for skill in card.skills)
        lines.append(f"- {name}: {card.description} (skills: {skills})")
    return "\n".join(lines)


def _parse_plan(raw: str) -> list[PlannedCall]:
    """Responsible for extracting a list of PlannedCall dicts from raw LLM response text."""
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
    """Responsible for producing an ordered list of agent calls for a given task using an LLM."""
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
    known = [call for call in plan if call["agent"] in cards]
    return known[:max_calls]
