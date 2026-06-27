import asyncio
from asyncio import QueueShutDown

from a2a.server.events import Event, EventQueueLegacy, InMemoryQueueManager
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role, SendMessageRequest, TaskStatusUpdateEvent

from common.langgraph_executor import LangGraphExecutor, extract_last_text


class FakeGraph:
    """ainvoke가 고정된 어시스턴트 메시지를 돌려주는 가짜 LangGraph."""

    def __init__(self, reply_text, raises=None):
        self._reply_text = reply_text
        self._raises = raises

    async def ainvoke(self, state):
        if self._raises is not None:
            raise self._raises
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content=self._reply_text)]}


def _user_request(text):
    msg = Message(message_id="u1", role=Role.ROLE_USER, parts=[Part(text=text)])
    return SendMessageRequest(message=msg)


# NOTE: RequestContext는 첫 위치 인자로 call_context(ServerCallContext)를 요구한다.
# EventQueue는 InMemoryQueueManager.create_or_tap()으로 구체 큐(EventQueueLegacy)를 받는다.
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
        event_queue.task_done()  # dequeue 시 task_done() 을 한 건씩 호출하여 close()가 끝날 수 있게 한다.
    await closing_task
    return events


def test_extract_last_text_returns_final_message_content():
    # given
    from langchain_core.messages import AIMessage
    result = {"messages": [AIMessage(content="hello")]}

    # when
    text = extract_last_text(result)

    # then
    assert text == "hello"


async def test_executor_completes_task_with_graph_output():
    # given
    graph = FakeGraph(reply_text="researched answer")
    executor = LangGraphExecutor(graph)
    request = _user_request("research quantum computing")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then
    events = await _drain(event_queue)
    texts = []
    for ev in events:
        if isinstance(ev, TaskStatusUpdateEvent) and ev.status.message.parts:
            texts.append(ev.status.message.parts[0].text)
    assert "researched answer" in texts


async def test_executor_marks_failed_when_graph_raises():
    # given
    graph = FakeGraph(reply_text="", raises=RuntimeError("boom"))
    executor = LangGraphExecutor(graph)
    request = _user_request("anything")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = await InMemoryQueueManager().create_or_tap("t1")

    # when
    await executor.execute(context, event_queue)

    # then
    events = await _drain(event_queue)
    states = [ev.status.state for ev in events if isinstance(ev, TaskStatusUpdateEvent)]
    from a2a.types import TaskState
    assert TaskState.TASK_STATE_FAILED in states
