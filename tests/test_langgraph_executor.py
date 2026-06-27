import asyncio
from asyncio import QueueShutDown

from langchain_core.messages import AIMessage, ToolMessage

from a2a.server.events import Event, EventQueueLegacy, InMemoryQueueManager
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
    TaskStatusUpdateEvent,
)

from common.langgraph_executor import LangGraphExecutor


class FakeStreamingGraph:
    """astream이 미리 정한 chunk 시퀀스를 순서대로 내는 가짜 LangGraph."""

    def __init__(self, chunks, raises=None):
        self._chunks = chunks
        self._raises = raises

    async def astream(self, state, *, stream_mode):
        if self._raises is not None:
            raise self._raises
        for chunk in self._chunks:
            yield chunk


def _user_request(text):
    msg = Message(message_id="u1", role=Role.ROLE_USER, parts=[Part(text=text)])
    return SendMessageRequest(message=msg)


async def _drain(event_queue: EventQueueLegacy) -> list[Event]:
    # event_queue.close()는 모든 항목에 대한 task_done() 호출을 기다린다.
    closing_task = asyncio.create_task(event_queue.close())
    events = []
    while True:
        try:
            event = await event_queue.dequeue_event()
        except QueueShutDown:  # 큐가 비면 close()가 예외를 던지므로 큐 소비를 끝낸다.
            break
        events.append(event)
        event_queue.task_done()
    await closing_task
    return events


def _status_events(events):
    return [e for e in events if isinstance(e, TaskStatusUpdateEvent)]


async def test_executor_emits_tool_call_status_update_with_metadata():
    # given — astream이 tool_call chunk 후 최종 chunk를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "quantum"}, "id": "c1", "type": "tool_call"}])]}},
        {"model": {"messages": [AIMessage(content="briefing done")]}},
    ])
    executor = LangGraphExecutor(graph)
    request = _user_request("research quantum")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then — 중간 tool_call status_update의 metadata가 구조화 dict로 실린다
    events = _status_events(await _drain(event_queue))
    working = [e for e in events
               if e.status.state == TaskState.TASK_STATE_WORKING and dict(e.status.message.metadata)]
    metadata = dict(working[0].status.message.metadata)
    assert metadata["kind"] == "tool_call"
    assert metadata["agent"] == "tavily"
    assert metadata["input"] == "quantum"


async def test_executor_emits_tool_result_status_update_with_metadata():
    # given — astream이 tool_result chunk를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"tools": {"messages": [ToolMessage(content="OUT[quantum]", name="tavily", tool_call_id="c1")]}},
        {"model": {"messages": [AIMessage(content="briefing done")]}},
    ])
    executor = LangGraphExecutor(graph)
    request = _user_request("research quantum")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then
    events = _status_events(await _drain(event_queue))
    result_meta = [dict(e.status.message.metadata) for e in events
                   if dict(e.status.message.metadata).get("kind") == "tool_result"]
    assert result_meta[0]["agent"] == "tavily"
    assert result_meta[0]["output"] == "OUT[quantum]"


async def test_executor_completes_with_final_text():
    # given — tool 사용 후 최종 텍스트를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "q"}, "id": "c1", "type": "tool_call"}])]}},
        {"model": {"messages": [AIMessage(content="final briefing")]}},
    ])
    executor = LangGraphExecutor(graph)
    request = _user_request("research")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then — 완료 상태에 최종 텍스트가 실린다
    events = _status_events(await _drain(event_queue))
    completed = [e for e in events if e.status.state == TaskState.TASK_STATE_COMPLETED]
    assert completed[-1].status.message.parts[0].text == "final briefing"


async def test_executor_marks_failed_when_graph_raises():
    # given — astream 진입 시 예외를 던지는 graph
    graph = FakeStreamingGraph(chunks=[], raises=RuntimeError("boom"))
    executor = LangGraphExecutor(graph)
    request = _user_request("anything")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then
    events = _status_events(await _drain(event_queue))
    states = [e.status.state for e in events]
    assert TaskState.TASK_STATE_FAILED in states
