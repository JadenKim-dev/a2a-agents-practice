from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from a2a.types import Message, Part, Role, StreamResponse, Task, TaskStatus, TaskState

from common.agent_card import build_agent_card
from orchestrator.client import extract_response_text
from orchestrator.orchestrate import run_task


class ToolCallingFakeModel(GenericFakeChatModel):
    """bind_tools를 self로 돌려 scripted 메시지로 ReAct 루프를 결정론적으로 구동하는 가짜 모델."""

    def bind_tools(self, tools, **kwargs):
        return self


def _cards():
    return {
        "research": build_agent_card(
            name="research", description="researches topics",
            url="http://127.0.0.1:9001/", skill_id="research",
            skill_name="Web Research", skill_description="web research",
            skill_tags=["research"],
        ),
        "summarizer": build_agent_card(
            name="summarizer", description="summarizes text",
            url="http://127.0.0.1:9002/", skill_id="summarize",
            skill_name="Summarize", skill_description="summarize text",
            skill_tags=["summarize"],
        ),
    }


def test_extract_response_text_reads_task_status_message():
    # given — 서버가 보내는 완료 Task를 흉내
    agent_msg = Message(
        message_id="a1",
        role=Role.ROLE_AGENT,
        parts=[Part(text="final answer")],
    )
    task = Task(
        id="t1",
        context_id="c1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=agent_msg),
    )
    response = StreamResponse(task=task)

    # when
    text = extract_response_text(response)

    # then
    assert text == "final answer"


async def test_run_task_returns_no_agents_message_when_discovery_empty(monkeypatch):
    # given — discover가 빈 dict를 반환
    async def empty_discover(http):
        return {}
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", empty_discover)

    # when
    answer = await run_task("any task", model=ToolCallingFakeModel(messages=iter([])))

    # then
    assert answer == "No agents available."


async def test_run_task_chains_tools_and_returns_final_answer(monkeypatch):
    # given — discover는 두 카드를, 원격 호출은 가짜로, LLM은 research→summarizer→최종답변 순으로 흉내
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    tool_calls = []

    async def fake_call_agent(http, card, text):
        tool_calls.append((card.name, text))
        return f"OUT[{text}]"
    monkeypatch.setattr("orchestrator.agent_tool.call_agent", fake_call_agent)

    fake_model = ToolCallingFakeModel(messages=iter([
        AIMessage(content="", tool_calls=[
            {"name": "research", "args": {"input": "quantum computing"},
             "id": "c1", "type": "tool_call"}]),
        AIMessage(content="", tool_calls=[
            {"name": "summarizer", "args": {"input": "OUT[quantum computing]"},
             "id": "c2", "type": "tool_call"}]),
        AIMessage(content="final synthesized answer"),
    ]))

    # when
    answer = await run_task("research and summarize quantum computing", model=fake_model)

    # then
    assert tool_calls[0] == ("research", "quantum computing")
    assert tool_calls[1] == ("summarizer", "OUT[quantum computing]")
    assert answer == "final synthesized answer"


async def test_run_task_returns_step_limit_message_on_recursion(monkeypatch):
    # given — LLM이 끝없이 research를 호출하도록 흉내, recursion_limit=2로 강제 초과
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    async def fake_call_agent(http, card, text):
        return "more"
    monkeypatch.setattr("orchestrator.agent_tool.call_agent", fake_call_agent)

    def endless_tool_calls():
        while True:
            yield AIMessage(content="", tool_calls=[
                {"name": "research", "args": {"input": "again"},
                 "id": "c", "type": "tool_call"}])
    fake_model = ToolCallingFakeModel(messages=endless_tool_calls())

    # when
    answer = await run_task("loop forever", model=fake_model, recursion_limit=2)

    # then
    assert answer == "Orchestration exceeded the step limit."
