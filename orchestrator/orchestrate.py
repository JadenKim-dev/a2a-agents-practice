"""Task를 ReAct 에이전트로 스트리밍 오케스트레이션해 진행 이벤트를 흘린다."""
from collections.abc import AsyncIterator

import httpx
from langchain.agents import create_agent

from orchestrator.registry import discover_agents
from orchestrator.agent_tool import build_agent_tool
from orchestrator.client import call_agent
from orchestrator.middleware import StepLimitSynthesisMiddleware
from orchestrator.events import ProgressEvent, to_progress_event, final_event, error_event

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are an orchestrator with access to specialist agent tools. "
    "Use the tools to fulfill the user's task, feeding one tool's output "
    "into the next as needed, then write the final answer for the user."
)

# 원격 에이전트는 웹 검색·LLM 호출로 수 초~수십 초가 걸리므로 httpx 기본 5초로는 부족하다.
AGENT_REQUEST_TIMEOUT_SECONDS = 60.0


async def run_task_stream(
    task: str,
    model=None,
    model_call_limit: int = 5,
    recursion_limit: int = 25,
) -> AsyncIterator[ProgressEvent]:
    """Task에 대해 discover→build→ReAct astream을 수행하며 진행 이벤트를 yield한다."""
    async with httpx.AsyncClient(timeout=AGENT_REQUEST_TIMEOUT_SECONDS) as http:
        cards = await discover_agents(http)
        if not cards:
            yield final_event("No agents available.", truncated=False)
            return
        graph = build_orchestrator_graph(http, cards, model, model_call_limit)
        try:
            async for chunk in graph.astream(
                {"messages": [{"role": "user", "content": task}]},
                {"recursion_limit": recursion_limit},
                stream_mode="updates",
            ):
                event = to_progress_event(chunk)
                if event is not None:
                    yield event
        except Exception as error:  # noqa: BLE001 — 스트림 무중단 보장
            yield error_event(str(error))


def build_orchestrator_graph(http, cards, model=None, model_call_limit: int = 5):
    """discover된 카드마다 원격 호출 tool을 만들고 종합 미들웨어를 붙여 ReAct 그래프를 만든다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    tools = [build_agent_tool(http, name, card, call_agent_fn=call_agent)
             for name, card in cards.items()]
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        middleware=[StepLimitSynthesisMiddleware(model_call_limit)],
    )
