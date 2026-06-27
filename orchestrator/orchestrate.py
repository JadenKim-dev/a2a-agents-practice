"""과업을 discover→plan→execute→synthesize로 수행하는 오케스트레이션 책임."""
import httpx

from orchestrator.registry import discover_agents
from orchestrator.client import call_agent
from orchestrator.llm import message_content_to_text
from orchestrator.planner import plan_calls, PREVIOUS_OUTPUT_PLACEHOLDER

SYNTHESIS_SYSTEM_PROMPT = (
    "You are an orchestrator. Given the original task and the outputs collected "
    "from sub-agents, write the final answer for the user."
)


async def execute_plan(http, cards, plan, call_agent_fn=call_agent) -> list[dict]:
    """Responsible for executing a plan sequentially, chaining each step's output into the next."""
    steps: list[dict] = []
    previous_output = ""
    for call in plan:
        resolved_input = call["input"].replace(
            PREVIOUS_OUTPUT_PLACEHOLDER, previous_output
        )
        try:
            output = await call_agent_fn(http, cards[call["agent"]], resolved_input)
        except Exception as error:  # noqa: BLE001
            output = f"[error calling {call['agent']}: {error}]"
        steps.append(
            {"agent": call["agent"], "input": resolved_input, "output": output}
        )
        previous_output = output
    return steps


async def synthesize(task: str, steps: list[dict], model=None) -> str:
    """Responsible for combining collected step outputs into a final answer using an LLM."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    collected = "\n\n".join(
        f"[{step['agent']}] {step['output']}" for step in steps
    )
    response = await model.ainvoke(
        [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\nOutputs:\n{collected}"},
        ]
    )
    return message_content_to_text(response)


async def run_task(task: str, model=None) -> str:
    """Responsible for running the full discover→plan→execute→synthesize pipeline for a task."""
    async with httpx.AsyncClient() as http:
        cards = await discover_agents(http)
        if not cards:
            return "No agents available."
        plan = await plan_calls(task, cards, model=model)
        if not plan:
            return "Planner produced no executable calls."
        steps = await execute_plan(http, cards, plan)
        return await synthesize(task, steps, model=model)
