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
    return [event for event in events if isinstance(event, TaskStatusUpdateEvent)]


async def _run_executor(graph) -> list[TaskStatusUpdateEvent]:
    # graph로 executor를 실행하고 방출된 status 이벤트를 반환한다.
    executor = LangGraphExecutor(graph)
    request = _user_request("research")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")
    await executor.execute(context, event_queue)
    return _status_events(await _drain(event_queue))


async def test_executor_emits_tool_call_status_update_with_metadata():
    # given — astream이 tool_call chunk 후 최종 chunk를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "quantum"}, "id": "c1", "type": "tool_call"}])]}},
        {"model": {"messages": [AIMessage(content="briefing done")]}},
    ])

    # when
    events = await _run_executor(graph)

    # then — 중간 tool_call status_update의 metadata가 구조화 dict로 실린다
    working_events = [event for event in events
               if event.status.state == TaskState.TASK_STATE_WORKING and dict(event.status.message.metadata)]
    metadata = dict(working_events[0].status.message.metadata)
    assert metadata["kind"] == "tool_call"
    assert metadata["agent"] == "tavily"
    assert metadata["input"] == "quantum"


async def test_executor_emits_tool_result_status_update_with_metadata():
    # given — astream이 tool_result chunk를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"tools": {"messages": [ToolMessage(content="OUT[quantum]", name="tavily", tool_call_id="c1")]}},
        {"model": {"messages": [AIMessage(content="briefing done")]}},
    ])

    # when
    events = await _run_executor(graph)

    # then
    tool_result_metadatas = [dict(event.status.message.metadata) for event in events
                   if dict(event.status.message.metadata).get("kind") == "tool_result"]
    assert tool_result_metadatas[0]["agent"] == "tavily"
    assert tool_result_metadatas[0]["output"] == "OUT[quantum]"


async def test_executor_completes_with_final_text():
    # given — tool 사용 후 최종 텍스트를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "q"}, "id": "c1", "type": "tool_call"}])]}},
        {"model": {"messages": [AIMessage(content="final briefing")]}},
    ])

    # when
    events = await _run_executor(graph)

    # then — 완료 상태에 최종 텍스트가 실린다
    completed_events = [event for event in events if event.status.state == TaskState.TASK_STATE_COMPLETED]
    assert completed_events[-1].status.message.parts[0].text == "final briefing"


async def test_executor_marks_failed_when_graph_raises():
    # given — astream 진입 시 예외를 던지는 graph
    graph = FakeStreamingGraph(chunks=[], raises=RuntimeError("boom"))

    # when
    events = await _run_executor(graph)

    # then
    states = [event.status.state for event in events]
    assert TaskState.TASK_STATE_FAILED in states
