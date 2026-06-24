import pytest

from a2a.server.events import EventQueue
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role, SendMessageRequest

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


# NOTE: RequestContext requires call_context as first positional arg (ServerCallContext).
# EventQueue is abstract; EventQueueLegacy is returned when instantiating EventQueue().
# EventQueueLegacy has no .empty() or .dequeue_event(no_wait=...) — drain via .queue.get_nowait().
async def _drain(event_queue):
    events = []
    while not event_queue.queue.empty():
        events.append(event_queue.queue.get_nowait())
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
    event_queue = EventQueue()

    # when
    await executor.execute(context, event_queue)

    # then
    events = await _drain(event_queue)
    texts = []
    for ev in events:
        status = getattr(ev, "status", None)
        if status and status.message and status.message.parts:
            texts.append(status.message.parts[0].text)
    assert "researched answer" in texts


async def test_executor_marks_failed_when_graph_raises():
    # given
    graph = FakeGraph(reply_text="", raises=RuntimeError("boom"))
    executor = LangGraphExecutor(graph)
    request = _user_request("anything")
    context = RequestContext(call_context=ServerCallContext(), request=request)
    event_queue = EventQueue()

    # when
    await executor.execute(context, event_queue)

    # then
    events = await _drain(event_queue)
    states = [ev.status.state for ev in events if getattr(ev, "status", None)]
    from a2a.types import TaskState
    assert TaskState.TASK_STATE_FAILED in states
