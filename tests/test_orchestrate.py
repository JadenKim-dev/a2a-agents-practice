from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from a2a.types import Message, Part, Role, StreamResponse, Task, TaskStatus, TaskState

from common.agent_card import build_agent_card
from orchestrator.client import extract_response_text
from orchestrator.orchestrate import run_task_stream


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


async def _collect(stream):
    return [event async for event in stream]


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


async def test_run_task_stream_yields_single_final_event_when_discovery_empty(monkeypatch):
    # given — discover가 빈 dict를 반환
    async def empty_discover(http):
        return {}
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", empty_discover)

    # when
    events = await _collect(run_task_stream("any task", model=None))

    # then
    assert len(events) == 1
    assert events[0].type == "final"
    assert events[0].content == "No agents available."
    assert events[0].truncated is False


async def test_run_task_stream_emits_tool_call_result_and_final_events(monkeypatch):
    # given — discover는 두 카드, 원격 호출은 가짜, LLM은 research→summarizer→최종답변 순
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    async def fake_call_agent(http, card, text, on_event=None):
        return f"OUT[{text}]"
    monkeypatch.setattr("orchestrator.orchestrate.call_agent", fake_call_agent)

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
    events = await _collect(run_task_stream(
        "research and summarize quantum computing", model=fake_model))

    # then
    event_types = [event.type for event in events]
    assert event_types == ["tool_call", "tool_result", "tool_call", "tool_result", "final"]
    assert events[0].agent == "research"
    assert events[0].input == "quantum computing"
    assert events[1].output == "OUT[quantum computing]"
    assert events[-1].content == "final synthesized answer"
    assert events[-1].truncated is False


async def test_run_task_stream_emits_truncated_final_event_when_step_limit_hit(monkeypatch):
    # given — 1번째 스텝은 tool_call, model_call_limit=2가 2번째 스텝의 도구를 비워 종합을 강제
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    async def fake_call_agent(http, card, text, on_event=None):
        return "more"
    monkeypatch.setattr("orchestrator.orchestrate.call_agent", fake_call_agent)

    fake_model = ToolCallingFakeModel(messages=iter([
        AIMessage(content="", tool_calls=[
            {"name": "research", "args": {"input": "again"},
             "id": "c", "type": "tool_call"}]),
        AIMessage(content="best-effort partial answer"),
    ]))

    # when
    events = await _collect(run_task_stream(
        "loop forever", model=fake_model, model_call_limit=2, recursion_limit=25))

    # then
    assert events[-1].type == "final"
    assert events[-1].truncated is True
    assert events[-1].content == "best-effort partial answer"


async def test_run_task_stream_merges_sub_agent_events_with_path(monkeypatch):
    # given — research 호출 중 서브 tool 진행 2건을 콜백하는 가짜 call_agent
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    async def fake_call_agent(http, card, text, on_event=None):
        if on_event is not None:
            on_event({"kind": "tool_call", "agent": "tavily", "input": "quantum"})
            on_event({"kind": "tool_result", "agent": "tavily", "output": "OUT[quantum]"})
        return "briefing"
    monkeypatch.setattr("orchestrator.orchestrate.call_agent", fake_call_agent)

    fake_model = ToolCallingFakeModel(messages=iter([
        AIMessage(content="", tool_calls=[
            {"name": "research", "args": {"input": "quantum computing"},
             "id": "c1", "type": "tool_call"}]),
        AIMessage(content="final answer"),
    ]))

    # when
    events = await _collect(run_task_stream("research quantum", model=fake_model))

    # then — 서브 tavily 이벤트가 path=["research"]로 섞여 나오고, 로컬 이벤트는 path가 없다
    sub_events = [e for e in events if e.path == ["research"]]
    assert [e.type for e in sub_events] == ["tool_call", "tool_result"]
    assert sub_events[0].agent == "tavily"
    assert sub_events[1].output == "OUT[quantum]"
    local_tool_calls = [e for e in events if e.type == "tool_call" and e.path is None]
    assert local_tool_calls[0].agent == "research"
    assert events[-1].type == "final"
    assert events[-1].content == "final answer"
