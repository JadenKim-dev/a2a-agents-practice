"""Task를 ReAct 에이전트로 오케스트레이션해 동적 라우팅·종합을 수행한다."""
import httpx
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from orchestrator.registry import discover_agents
from orchestrator.agent_tool import build_agent_tool
from orchestrator.llm import message_content_to_text

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are an orchestrator with access to specialist agent tools. "
    "Use the tools to fulfill the user's task, feeding one tool's output "
    "into the next as needed, then write the final answer for the user."
)


async def run_task(task: str, model=None, recursion_limit: int = 10) -> str:
    """Task에 대해 discover→build→ReAct 실행 전체 파이프라인을 수행한다."""
    async with httpx.AsyncClient() as http:
        cards = await discover_agents(http)
        if not cards:
            return "No agents available."
        graph = build_orchestrator_graph(http, cards, model)
        try:
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": task}]},
                {"recursion_limit": recursion_limit},
            )
        except GraphRecursionError:
            return "Orchestration exceeded the step limit."
        return message_content_to_text(result["messages"][-1])


def build_orchestrator_graph(http, cards, model=None):
    """discover된 카드마다 원격 호출 tool을 만들어 ReAct 에이전트 그래프를 생성한다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    tools = [build_agent_tool(http, name, card) for name, card in cards.items()]
    return create_agent(
        model=model, tools=tools, system_prompt=ORCHESTRATOR_SYSTEM_PROMPT
    )
