# 에이전트 간 통신 스트리밍 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서브 에이전트(Research, Summarizer)의 툴 호출/결과를 A2A `status_update`로 실시간 발행하고, 오케스트레이터가 이를 받아 계층 경로(`path`)를 붙여 `POST /run` SSE 스트림에 흘려보낸다.

**Architecture:** 서브 에이전트 서버의 `LangGraphExecutor`를 `ainvoke`에서 `astream`으로 전환해 중간 tool 이벤트를 `update_status(WORKING, metadata={...})`로 발행한다. 오케스트레이터 클라이언트는 `streaming=True`로 받아 `message.metadata`를 파싱해 콜백한다. agent_tool이 콜백 이벤트에 `path=[에이전트명]`을 붙여 `asyncio.Queue`에 넣고, `run_task_stream`이 ReAct astream chunk와 이 큐를 시간순으로 병합해 yield한다.

**Tech Stack:** Python 3.14, a2a-sdk 1.1.0 (protobuf 타입), LangGraph (`langchain.agents.create_agent`, `astream(stream_mode="updates")`), FastAPI + sse-starlette, pytest (asyncio).

## Global Constraints

- a2a-sdk는 **1.1.0 고정**, protobuf 타입 기반. `Message`는 `parts=`, metadata dict는 protobuf `Struct`로 변환됨(`.get()` 없음 → `dict(metadata)`로 변환 후 사용).
- 테스트는 OpenAI/Tavily 등 실제 외부 호출을 가짜로 대체해 **결정론적**으로 작성. 실제 키 호출은 수동 E2E만.
- 각 테스트 케이스는 `# given` / `# when` / `# then` 주석으로 구획. 입력 리터럴은 `it`(테스트 함수) 내부에 둔다.
- docstring/주석은 한글, 책임을 서술하는 평서형(`~한다`)으로 작성.
- 선언 순서: static→instance, field→method, public→private, caller→callee.
- 모듈 경계 import만 alias 없이 기존 코드 컨벤션(`from common.x import ...`, `from orchestrator.x import ...`)을 그대로 따른다.
- 테스트 실행 전 `source .venv/bin/activate`. 테스트 명령은 `pytest`.

---

## File Structure

- **Create** `common/graph_progress.py` — LangGraph `astream` chunk를 프레임워크 중립 진행 정보(`GraphStep`)로 추출하는 순수 함수. executor와 orchestrator events가 공유.
- **Create** `tests/test_graph_progress.py` — 위 추출 함수 테스트.
- **Create** `tests/test_client.py` — client의 streaming 수신/콜백 테스트.
- **Modify** `orchestrator/events.py` — `ProgressEvent.path` 추가, `_message_to_event`를 `common/graph_progress.py` 추출 함수 위에 재작성.
- **Modify** `common/langgraph_executor.py` — `ainvoke`→`astream` 전환, 중간 `update_status(metadata=...)` 발행.
- **Modify** `orchestrator/client.py` — `streaming=True`, `call_agent(..., on_event=...)`, `extract_progress_metadata` 추가.
- **Modify** `orchestrator/agent_tool.py` — 이벤트 싱크 주입, 서브 이벤트에 `path` 부여.
- **Modify** `orchestrator/orchestrate.py` — `asyncio.Queue`로 ReAct chunk와 서브 이벤트 병합.
- **Modify** `tests/test_events.py`, `tests/test_langgraph_executor.py`, `tests/test_agent_tool.py`, `tests/test_orchestrate.py` — 시그니처/동작 변경 반영.

---

## Task 1: `ProgressEvent.path` 필드 추가

진행 이벤트에 출처 계층 경로를 담아, 서브 에이전트 이벤트를 오케스트레이터 로컬 이벤트와 구분한다.

**Files:**
- Modify: `orchestrator/events.py`
- Test: `tests/test_events.py`, `tests/test_orchestrator_server.py`

**Interfaces:**
- Produces: `ProgressEvent`에 `path: list[str] | None = None` 필드. `None`이면 직렬화 시 제외(기존 `event_to_payload` 동작).

- [ ] **Step 1: path 직렬화 테스트 추가 (실패)**

`tests/test_orchestrator_server.py`에 추가:

```python
def test_event_to_payload_includes_path_when_present():
    # given — path가 있는 tool_call 이벤트
    from orchestrator.events import ProgressEvent
    event = ProgressEvent(type="tool_call", agent="tavily", input="quantum", path=["research"])

    # when
    payload = json.loads(event_to_payload(event))

    # then
    assert payload == {"type": "tool_call", "agent": "tavily", "input": "quantum", "path": ["research"]}


def test_event_to_payload_omits_path_when_none():
    # given — path가 없는 final 이벤트
    event = final_event(content="done", truncated=False)

    # when
    payload = json.loads(event_to_payload(event))

    # then
    assert "path" not in payload
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_orchestrator_server.py::test_event_to_payload_includes_path_when_present -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'path'`

- [ ] **Step 3: `ProgressEvent`에 `path` 필드 추가**

`orchestrator/events.py`의 `ProgressEvent` dataclass에 필드 추가(`message` 아래):

```python
@dataclass
class ProgressEvent:
    """오케스트레이션 진행의 한 스텝을 표현한다."""
    type: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool | None = None
    message: str | None = None
    path: list[str] | None = None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_orchestrator_server.py -v`
Expected: PASS (신규 2개 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add orchestrator/events.py tests/test_orchestrator_server.py
git commit -m "feat: ProgressEvent에 출처 계층 경로 path 필드 추가"
```

---

## Task 2: chunk 추출 순수 함수 공통화 (`common/graph_progress.py`)

서브 에이전트 graph와 오케스트레이터 graph는 모두 LangGraph라 `astream(stream_mode="updates")` chunk 형태가 같다. chunk 한 개를 프레임워크 중립 진행 정보로 추출하는 순수 함수를 만들어 executor와 events가 공유한다.

**Files:**
- Create: `common/graph_progress.py`
- Test: `tests/test_graph_progress.py`

**Interfaces:**
- Produces:
  - `@dataclass GraphStep` — 필드: `kind: str` (`"tool_call"` | `"tool_result"` | `"final"`), `agent: str | None`, `input: str | None`, `output: str | None`, `content: str | None`, `truncated: bool`.
  - `def extract_graph_step(chunk: dict) -> GraphStep | None` — chunk 한 개에서 첫 매핑 가능한 메시지를 `GraphStep`으로 변환. 없으면 `None`.

- [ ] **Step 1: 추출 함수 테스트 작성 (실패)**

`tests/test_graph_progress.py` 생성:

```python
from langchain_core.messages import AIMessage, ToolMessage

from common.graph_progress import extract_graph_step


def test_extract_graph_step_maps_tool_call():
    # given — tool_calls를 가진 AIMessage chunk
    chunk = {"model": {"messages": [
        AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "quantum"}, "id": "c1", "type": "tool_call"}])]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "tool_call"
    assert step.agent == "tavily"
    assert step.input == "quantum"


def test_extract_graph_step_maps_tool_result():
    # given — ToolMessage chunk
    chunk = {"tools": {"messages": [
        ToolMessage(content="OUT[quantum]", name="tavily", tool_call_id="c1")]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "tool_result"
    assert step.agent == "tavily"
    assert step.output == "OUT[quantum]"


def test_extract_graph_step_maps_final_message():
    # given — tool_calls 없는 최종 AIMessage chunk
    chunk = {"model": {"messages": [AIMessage(content="final answer")]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "final"
    assert step.content == "final answer"
    assert step.truncated is False


def test_extract_graph_step_reads_truncated_from_response_metadata():
    # given — truncated 마킹이 붙은 최종 AIMessage chunk
    message = AIMessage(content="partial")
    message.response_metadata = {"truncated": True}
    chunk = {"model": {"messages": [message]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "final"
    assert step.truncated is True


def test_extract_graph_step_returns_none_for_empty_chunk():
    # given — 매핑 대상이 없는 chunk
    chunk = {"model": {"messages": []}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_graph_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.graph_progress'`

- [ ] **Step 3: `common/graph_progress.py` 구현**

```python
"""LangGraph astream chunk를 프레임워크 중립 진행 정보로 추출한다."""
from dataclasses import dataclass

from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.llm import message_content_to_text


@dataclass
class GraphStep:
    """LangGraph 한 스텝의 진행 정보를 프레임워크 중립적으로 표현한다."""
    kind: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool = False


def extract_graph_step(chunk: dict) -> GraphStep | None:
    """astream updates chunk 하나에서 첫 매핑 가능한 메시지를 GraphStep으로 추출한다. 없으면 None을 반환한다."""
    for update in chunk.values():
        for message in update.get("messages", []):
            step = _message_to_step(message)
            if step is not None:
                return step
    return None


def _message_to_step(message) -> GraphStep | None:
    if isinstance(message, AIMessage) and message.tool_calls:
        call = message.tool_calls[0]
        return GraphStep(kind="tool_call", agent=call["name"], input=call["args"].get("input", ""))
    if isinstance(message, ToolMessage):
        return GraphStep(kind="tool_result", agent=message.name or "unknown",
                         output=message_content_to_text(message))
    if isinstance(message, AIMessage):
        truncated = bool(message.response_metadata.get("truncated", False))
        return GraphStep(kind="final", content=message_content_to_text(message), truncated=truncated)
    return None
```

참고: `orchestrator.llm.message_content_to_text`는 LangChain 메시지 content를 문자열로 평탄화하는 기존 헬퍼다(이미 존재).

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_graph_progress.py -v`
Expected: PASS (5개 전부)

- [ ] **Step 5: 커밋**

```bash
git add common/graph_progress.py tests/test_graph_progress.py
git commit -m "feat: LangGraph chunk 추출 순수 함수 graph_progress 추가"
```

---

## Task 3: `events.py`를 `graph_progress` 위에 재작성

오케스트레이터 events의 chunk→이벤트 변환을 Task 2의 추출 함수 위에 다시 얹어 로직 중복을 제거한다. 동작은 그대로 유지하되 내부 구현만 위임한다.

**Files:**
- Modify: `orchestrator/events.py`
- Test: `tests/test_events.py` (기존 테스트가 회귀 가드)

**Interfaces:**
- Consumes: `common.graph_progress.extract_graph_step`, `GraphStep`.
- Produces: `to_progress_event(chunk) -> ProgressEvent | None` (시그니처/동작 불변), 기존 `tool_call_event`/`tool_result_event`/`final_event`/`error_event` 그대로 유지.

- [ ] **Step 1: 기존 events 테스트가 통과하는지 먼저 확인 (회귀 기준선)**

Run: `source .venv/bin/activate && pytest tests/test_events.py -v`
Expected: PASS (5개 — 기준선 확보)

- [ ] **Step 2: `to_progress_event`를 추출 함수 위로 재작성**

`orchestrator/events.py`에서 import 교체 및 `to_progress_event`/`_message_to_event` 재작성:

```python
"""ReAct 스트림 chunk를 사용자에게 노출할 진행 이벤트로 변환한다."""
from dataclasses import dataclass

from common.graph_progress import GraphStep, extract_graph_step


@dataclass
class ProgressEvent:
    """오케스트레이션 진행의 한 스텝을 표현한다."""
    type: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool | None = None
    message: str | None = None
    path: list[str] | None = None


def to_progress_event(chunk: dict) -> ProgressEvent | None:
    """astream updates chunk 하나를 진행 이벤트로 변환한다. 매핑 대상이 없으면 None을 반환한다."""
    step = extract_graph_step(chunk)
    if step is None:
        return None
    return step_to_progress_event(step)


def step_to_progress_event(step: GraphStep, path: list[str] | None = None) -> ProgressEvent:
    """GraphStep을 오케스트레이터 진행 이벤트로 감싼다. path가 주어지면 출처 경로로 부여한다."""
    if step.kind == "tool_call":
        return ProgressEvent(type="tool_call", agent=step.agent, input=step.input, path=path)
    if step.kind == "tool_result":
        return ProgressEvent(type="tool_result", agent=step.agent, output=step.output, path=path)
    return ProgressEvent(type="final", content=step.content, truncated=step.truncated, path=path)


def tool_call_event(agent: str, input: str) -> ProgressEvent:
    """LLM이 에이전트 tool 호출을 결정한 스텝 이벤트를 만든다."""
    return ProgressEvent(type="tool_call", agent=agent, input=input)


def tool_result_event(agent: str, output: str) -> ProgressEvent:
    """원격 에이전트 호출 결과를 관찰한 스텝 이벤트를 만든다."""
    return ProgressEvent(type="tool_result", agent=agent, output=output)


def final_event(content: str, truncated: bool) -> ProgressEvent:
    """ReAct 종료(또는 강제 종합)의 최종 답변 이벤트를 만든다."""
    return ProgressEvent(type="final", content=content, truncated=truncated)


def error_event(message: str) -> ProgressEvent:
    """스트림 도중 발생한 예외를 알리는 이벤트를 만든다."""
    return ProgressEvent(type="error", message=message)
```

참고: 기존 `from langchain_core.messages import AIMessage, ToolMessage`와 `from orchestrator.llm import message_content_to_text` import는 events.py에서 더 이상 쓰지 않으므로 제거한다(위 코드가 전체 파일 내용).

- [ ] **Step 3: 기존 + 신규 events 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_events.py -v`
Expected: PASS (기존 5개 — `to_progress_event` 동작 불변)

`tests/test_events.py`에 `step_to_progress_event`의 path 부여를 검증하는 케이스 추가:

```python
def test_step_to_progress_event_attaches_path():
    # given — tool_call GraphStep과 출처 경로
    from common.graph_progress import GraphStep
    from orchestrator.events import step_to_progress_event
    step = GraphStep(kind="tool_call", agent="tavily", input="quantum")

    # when
    event = step_to_progress_event(step, path=["research"])

    # then
    assert event.type == "tool_call"
    assert event.agent == "tavily"
    assert event.input == "quantum"
    assert event.path == ["research"]
```

- [ ] **Step 4: 추가 테스트까지 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_events.py -v`
Expected: PASS (6개)

- [ ] **Step 5: 커밋**

```bash
git add orchestrator/events.py tests/test_events.py
git commit -m "refactor: events를 graph_progress 위에 재작성하고 path 부여 추가"
```

---

## Task 4: `LangGraphExecutor` astream 전환 + 중간 status_update 발행

서브 에이전트 서버가 graph를 스트리밍 실행하며 tool 호출/결과를 `update_status(WORKING, metadata={...})`로 발행하고, 최종 텍스트만 `complete()`로 마감한다.

**Files:**
- Modify: `common/langgraph_executor.py`
- Test: `tests/test_langgraph_executor.py`

**Interfaces:**
- Consumes: `common.graph_progress.extract_graph_step`, `GraphStep`.
- Produces: 중간 이벤트의 `status.message.metadata`는 `{"kind","agent","input"|"output"}` dict. 최종 텍스트는 `complete()`로 전달.
- `InvocableGraph` Protocol을 `astream`을 요구하도록 변경: `def astream(self, state: dict, *, stream_mode: str) -> AsyncIterator[dict]`.

- [ ] **Step 1: 가짜 graph를 astream 기반으로 바꾸고 실패 테스트 작성**

`tests/test_langgraph_executor.py` 상단 `FakeGraph`를 astream 기반으로 교체하고, `extract_last_text` 직접 테스트는 제거(해당 함수가 사라지므로). 다음으로 전체 교체:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_langgraph_executor.py -v`
Expected: FAIL — 현재 executor는 `ainvoke`를 호출하므로 `FakeStreamingGraph`에 `ainvoke`가 없어 `AttributeError`, 그리고 import한 `extract_last_text` 제거로 ImportError가 날 수 있음(아래 구현에서 함께 정리).

- [ ] **Step 3: `LangGraphExecutor`를 astream 기반으로 재작성**

`common/langgraph_executor.py` 전체 교체:

```python
"""LangGraph 그래프를 A2A AgentExecutor로 변환하는 어댑터다."""
from collections.abc import AsyncIterator
from typing import Protocol

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.types import Part, TaskState

from common.graph_progress import GraphStep, extract_graph_step


class InvocableGraph(Protocol):
    """LangGraphExecutor가 그래프에 요구하는 최소 스트리밍 규약"""

    def astream(self, state: dict, *, stream_mode: str) -> AsyncIterator[dict]: ...


class LangGraphExecutor(AgentExecutor):
    """주입된 LangGraph 그래프를 스트리밍 실행해 중간 진행과 최종 결과를 A2A로 발행한다."""

    def __init__(self, graph: InvocableGraph):
        self._graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            if context.message is None:
                raise ValueError("request has neither a current task nor a user message")
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        user_text = context.get_user_input()
        final_text = ""
        try:
            async for chunk in self._graph.astream(
                {"messages": [{"role": "user", "content": user_text}]},
                stream_mode="updates",
            ):
                step = extract_graph_step(chunk)
                if step is None:
                    continue
                if step.kind == "final":
                    final_text = step.content or ""
                    continue
                await self._emit_step(updater, step)
        except Exception as error:  # noqa: BLE001 — 서버 무중단 보장
            await updater.failed(
                message=updater.new_agent_message(parts=[Part(text=f"agent error: {error}")])
            )
            return
        await updater.complete(
            message=updater.new_agent_message(parts=[Part(text=final_text)])
        )

    async def _emit_step(self, updater: TaskUpdater, step: GraphStep) -> None:
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=updater.new_agent_message(
                parts=[Part(text=step_summary(step))],
                metadata=step_metadata(step),
            ),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is out of scope for the PoC")


def step_metadata(step: GraphStep) -> dict:
    """GraphStep을 status_update에 실을 구조화 metadata dict로 변환한다."""
    if step.kind == "tool_call":
        return {"kind": "tool_call", "agent": step.agent or "", "input": step.input or ""}
    return {"kind": "tool_result", "agent": step.agent or "", "output": step.output or ""}


def step_summary(step: GraphStep) -> str:
    """GraphStep을 사람이 읽을 한 줄 요약 텍스트로 만든다."""
    if step.kind == "tool_call":
        return f"calling {step.agent}: {step.input or ''}"
    return f"{step.agent} returned: {step.output or ''}"
```

참고:
- `new_agent_message`는 `(parts, metadata=None)` 시그니처이므로 metadata를 dict로 직접 전달 가능(검증됨).
- 기존 `extract_last_text` 함수와 `InvocableGraph.ainvoke`는 제거된다(astream으로 최종 텍스트를 누적하므로 불필요).

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_langgraph_executor.py -v`
Expected: PASS (4개)

- [ ] **Step 5: 커밋**

```bash
git add common/langgraph_executor.py tests/test_langgraph_executor.py
git commit -m "feat: executor를 astream으로 전환해 중간 tool 진행을 status_update로 발행"
```

---

## Task 5: `client` streaming 수신 + `on_event` 콜백

오케스트레이터 클라이언트가 `streaming=True`로 서브 에이전트 스트림을 받아, `status_update`의 `message.metadata`에서 구조화 진행 정보를 꺼내 콜백한다. 최종 텍스트 반환은 유지한다.

**Files:**
- Modify: `orchestrator/client.py`
- Test: `tests/test_client.py` (신규), `tests/test_orchestrate.py`(기존 `extract_response_text` import 유지 확인)

**Interfaces:**
- Produces:
  - `async def call_agent(http_client, card, text, on_event=None) -> str` — `on_event: Callable[[dict], None] | None`. `status_update` 수신 시 `extract_progress_metadata`가 dict를 돌려주면 `on_event(dict)` 호출.
  - `def extract_progress_metadata(stream_response) -> dict | None` — `status_update`의 `message.metadata`에 `kind`가 있으면 dict, 아니면 `None`.
  - 기존 `extract_response_text(stream_response) -> str` 유지.

- [ ] **Step 1: client 테스트 작성 (실패)**

`tests/test_client.py` 생성:

```python
from a2a.types import (
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from orchestrator.client import extract_progress_metadata, extract_response_text


def _status_update_response(text, metadata):
    msg = Message(message_id="a1", role=Role.ROLE_AGENT, parts=[Part(text=text)], metadata=metadata)
    status = TaskStatus(state=TaskState.TASK_STATE_WORKING, message=msg)
    return StreamResponse(status_update=TaskStatusUpdateEvent(task_id="t1", context_id="c1", status=status))


def test_extract_progress_metadata_returns_dict_when_kind_present():
    # given — kind를 가진 status_update
    response = _status_update_response(
        "calling tavily", {"kind": "tool_call", "agent": "tavily", "input": "quantum"})

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata == {"kind": "tool_call", "agent": "tavily", "input": "quantum"}


def test_extract_progress_metadata_returns_none_when_no_metadata():
    # given — metadata 없는 status_update (표준 텍스트만)
    response = _status_update_response("plain progress text", None)

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata is None


def test_extract_progress_metadata_returns_none_for_completed_task():
    # given — 완료 Task payload (status_update 아님)
    msg = Message(message_id="a1", role=Role.ROLE_AGENT, parts=[Part(text="final")])
    task = Task(id="t1", context_id="c1",
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=msg))
    response = StreamResponse(task=task)

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata is None
```

`call_agent`의 콜백 동작은 가짜 A2A 클라이언트를 만들기 번거로우므로(ClientFactory 의존), 순수 함수 `extract_progress_metadata`/`extract_response_text` 단위 테스트로 검증한다. `call_agent`의 콜백 통합은 Task 7의 orchestrate 통합 테스트(가짜 `call_agent` 대체)에서 간접 커버된다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_progress_metadata'`

- [ ] **Step 3: `client.py` 재작성**

`orchestrator/client.py` 전체 교체:

```python
"""원격 A2A 에이전트에 메시지를 보내고 진행 콜백과 최종 응답 텍스트를 회수한다."""
from collections.abc import Callable

import httpx

from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, StreamResponse


async def call_agent(
    http_client: httpx.AsyncClient,
    card: AgentCard,
    text: str,
    on_event: Callable[[dict], None] | None = None,
) -> str:
    """원격 에이전트를 스트리밍 호출하며 진행 metadata를 on_event로 흘리고 최종 텍스트를 반환한다."""
    client_factory = ClientFactory(ClientConfig(httpx_client=http_client, streaming=True))
    client = client_factory.create(card)
    request = SendMessageRequest(
        message=Message(
            message_id="orchestrator-msg",
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )
    )
    final_text = ""
    async for event in client.send_message(request):
        if on_event is not None:
            metadata = extract_progress_metadata(event)
            if metadata is not None:
                on_event(metadata)
        extracted_response = extract_response_text(event)
        if extracted_response:
            final_text = extracted_response
    return final_text


def extract_progress_metadata(stream_response: StreamResponse) -> dict | None:
    """status_update의 message.metadata에서 진행 정보 dict를 꺼낸다. kind가 없으면 None을 반환한다."""
    if stream_response.WhichOneof("payload") != "status_update":
        return None
    message = stream_response.status_update.status.message
    if not message:
        return None
    metadata = dict(message.metadata)
    if "kind" not in metadata:
        return None
    return metadata


def extract_response_text(stream_response: StreamResponse) -> str:
    """완료 payload에서 최종 응답 텍스트를 꺼낸다. 없으면 빈 문자열을 반환한다."""
    payload_kind = stream_response.WhichOneof("payload")
    if payload_kind == "task":
        status = stream_response.task.status
        if status.message and status.message.parts:
            return status.message.parts[0].text
    if payload_kind == "message":
        parts = stream_response.message.parts
        if parts:
            return parts[0].text
    if payload_kind == "status_update":
        message = stream_response.status_update.status.message
        if message and message.parts:
            return message.parts[0].text
    return ""
```

주의: `extract_response_text`는 `status_update`의 텍스트도 회수하지만, 중간 진행 텍스트("calling tavily ...")가 `final_text`를 덮어쓸 수 있다. 그러나 완료는 `task`/`message`(또는 마지막 `status_update`)로 오고, 서버(executor)는 최종을 `complete()`(=completed Task/status)로 보내므로 마지막 회수값이 최종 텍스트가 된다. 회귀는 Task 7 통합 테스트로 가드한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_client.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add orchestrator/client.py tests/test_client.py
git commit -m "feat: client를 streaming 수신으로 전환하고 진행 metadata 콜백 추가"
```

---

## Task 6: `agent_tool` 이벤트 싱크 + `path` 부여

agent_tool이 서브 에이전트 호출 중 받은 진행 metadata에 `path=[에이전트명]`을 붙여 외부 싱크로 방출한다.

**Files:**
- Modify: `orchestrator/agent_tool.py`
- Test: `tests/test_agent_tool.py`

**Interfaces:**
- Consumes: `orchestrator.events.ProgressEvent`, `orchestrator.client.call_agent`(`on_event` 지원).
- Produces: `build_agent_tool(http, name, card, call_agent_fn=call_agent, emit=None) -> StructuredTool`. `emit: Callable[[ProgressEvent], None] | None`. 서브 진행 metadata는 `ProgressEvent(type=kind, agent=meta["agent"], input/output, path=[name])`로 변환되어 `emit` 호출.

- [ ] **Step 1: agent_tool 싱크 테스트 작성 (실패)**

`tests/test_agent_tool.py`에 추가:

```python
async def test_build_agent_tool_emits_sub_events_with_path():
    # given — 호출 중 진행 metadata를 콜백하는 가짜 call_agent와 이벤트 싱크
    card = _research_card()
    emitted = []

    async def fake_call_agent(http, card_arg, text, on_event=None):
        on_event({"kind": "tool_call", "agent": "tavily", "input": "quantum"})
        on_event({"kind": "tool_result", "agent": "tavily", "output": "OUT[quantum]"})
        return "briefing"

    tool = build_agent_tool(
        http="HTTP", name="research", card=card,
        call_agent_fn=fake_call_agent, emit=emitted.append,
    )

    # when
    output = await tool.ainvoke({"input": "quantum"})

    # then — 서브 이벤트가 path=["research"]로 방출되고 최종 텍스트는 반환된다
    assert output == "briefing"
    assert emitted[0].type == "tool_call"
    assert emitted[0].agent == "tavily"
    assert emitted[0].input == "quantum"
    assert emitted[0].path == ["research"]
    assert emitted[1].type == "tool_result"
    assert emitted[1].output == "OUT[quantum]"
    assert emitted[1].path == ["research"]
```

기존 `test_build_agent_tool_delegates_input_to_call_agent`와 `test_build_agent_tool_absorbs_call_failure_into_text`의 가짜 `call_agent`는 `on_event=None` 기본 인자를 받도록 시그니처를 `async def fake_call_agent(http, card_arg, text, on_event=None)`로 수정한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_agent_tool.py -v`
Expected: FAIL — `build_agent_tool`에 `emit` 인자 없음(`TypeError`), 기존 가짜 시그니처도 `on_event` 미수용.

- [ ] **Step 3: `agent_tool.py` 재작성**

`orchestrator/agent_tool.py` 전체 교체:

```python
"""원격 A2A 에이전트 카드를 ReAct가 호출 가능한 LLM tool로 변환한다."""
from collections.abc import Callable

from langchain_core.tools import StructuredTool

from a2a.types import AgentCard

from orchestrator.client import call_agent
from orchestrator.events import ProgressEvent


def build_agent_tool(
    http,
    name: str,
    card: AgentCard,
    call_agent_fn=call_agent,
    emit: Callable[[ProgressEvent], None] | None = None,
) -> StructuredTool:
    """원격 A2A 에이전트 하나를 ReAct가 호출 가능한 단일 인자 tool로 감싸고 서브 진행을 emit로 방출한다."""
    def on_sub_event(metadata: dict) -> None:
        if emit is None:
            return
        emit(sub_progress_event(name, metadata))

    async def call(input: str) -> str:
        try:
            return await call_agent_fn(http, card, input, on_event=on_sub_event)
        # 루프 무중단 보장: 예외를 그래프로 전파하지 않고 LLM이 관찰할 텍스트로 흡수한다.
        except Exception as error:  # noqa: BLE001
            return f"[error calling {name}: {error}]"
    return StructuredTool.from_function(
        coroutine=call,
        name=name,
        description=tool_description(card),
    )


def tool_description(card: AgentCard) -> str:
    """카드의 description과 skill 이름을 LLM tool description 문자열로 합친다."""
    skills = ", ".join(skill.name for skill in card.skills)
    return f"{card.description} (skills: {skills})"


def sub_progress_event(agent_name: str, metadata: dict) -> ProgressEvent:
    """서브 에이전트 진행 metadata를 path가 부여된 ProgressEvent로 변환한다."""
    return ProgressEvent(
        type=metadata["kind"],
        agent=metadata.get("agent"),
        input=metadata.get("input"),
        output=metadata.get("output"),
        path=[agent_name],
    )
```

참고: 기존 테스트의 가짜 `call_agent`가 `on_event` 키워드를 받도록 Step 1에서 수정했으므로 호환된다. 실제 `call_agent`(Task 5)는 `on_event`를 지원한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_agent_tool.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 커밋**

```bash
git add orchestrator/agent_tool.py tests/test_agent_tool.py
git commit -m "feat: agent_tool이 서브 진행을 path 부여해 방출하도록 확장"
```

---

## Task 7: `orchestrate` ReAct chunk + 서브 이벤트 큐 병합

`run_task_stream`이 ReAct astream chunk와 agent_tool이 큐에 넣는 서브 이벤트를 시간순으로 병합해 yield한다.

**Files:**
- Modify: `orchestrator/orchestrate.py`
- Test: `tests/test_orchestrate.py`

**Interfaces:**
- Consumes: `build_agent_tool(..., emit=queue_push)`, `to_progress_event`, `call_agent`(`on_event` 지원).
- Produces: `run_task_stream(task, model=None, model_call_limit=5, recursion_limit=25) -> AsyncIterator[ProgressEvent]` (시그니처 불변). 서브 이벤트는 `path`가 실린 채, 로컬 이벤트는 `path=None`인 채로 흘러나온다.

- [ ] **Step 1: 병합 동작 테스트 작성 (실패)**

`tests/test_orchestrate.py`의 가짜 `call_agent`들을 `on_event`를 받도록 고치고, 서브 이벤트 방출 케이스를 추가한다.

기존 `fake_call_agent` 시그니처를 모두 `async def fake_call_agent(http, card, text, on_event=None)`로 수정한다(3곳: empty-discovery 케이스 제외한 호출들). 그리고 서브 이벤트 병합 케이스 추가:

```python
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
```

기존 `test_run_task_stream_emits_tool_call_result_and_final_events`와 `test_run_task_stream_emits_truncated_final_event_when_step_limit_hit`의 가짜 `call_agent`도 `on_event=None` 인자를 받도록 수정한다(서브 이벤트는 방출 안 하므로 동작 불변).

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_orchestrate.py -v`
Expected: FAIL — 서브 이벤트가 yield되지 않아 `sub_events`가 비어 단언 실패. (기존 케이스는 시그니처 수정으로 통과.)

- [ ] **Step 3: `orchestrate.py` 병합 구현**

`orchestrator/orchestrate.py` 재작성(상단 import에 `asyncio` 추가, `build_orchestrator_graph`에 `emit` 연결, `run_task_stream`에 큐 병합):

```python
"""Task를 ReAct 에이전트로 스트리밍 오케스트레이션해 진행 이벤트를 흘린다."""
import asyncio
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

# astream 소비 종료를 병합 루프에 알리는 신호.
_STREAM_DONE = object()


async def run_task_stream(
    task: str,
    model=None,
    model_call_limit: int = 5,
    recursion_limit: int = 25,
) -> AsyncIterator[ProgressEvent]:
    """Task에 대해 ReAct astream과 서브 에이전트 이벤트 큐를 병합해 진행 이벤트를 yield한다."""
    async with httpx.AsyncClient(timeout=AGENT_REQUEST_TIMEOUT_SECONDS) as http:
        cards = await discover_agents(http)
        if not cards:
            yield final_event("No agents available.", truncated=False)
            return
        sub_event_queue: asyncio.Queue = asyncio.Queue()
        graph = build_orchestrator_graph(
            http, cards, model, model_call_limit, emit=sub_event_queue.put_nowait
        )
        async for event in _merge_stream(graph, task, recursion_limit, sub_event_queue):
            yield event


async def _merge_stream(graph, task, recursion_limit, sub_event_queue):
    """ReAct astream을 백그라운드로 돌리고, 서브 이벤트 큐와 시간순으로 합쳐 yield한다."""
    async def drive_graph():
        try:
            async for chunk in graph.astream(
                {"messages": [{"role": "user", "content": task}]},
                {"recursion_limit": recursion_limit},
                stream_mode="updates",
            ):
                event = to_progress_event(chunk)
                if event is not None:
                    sub_event_queue.put_nowait(event)
        except Exception as error:  # noqa: BLE001 — 스트림 무중단 보장
            sub_event_queue.put_nowait(error_event(str(error)))
        finally:
            sub_event_queue.put_nowait(_STREAM_DONE)

    graph_task = asyncio.create_task(drive_graph())
    try:
        while True:
            item = await sub_event_queue.get()
            if item is _STREAM_DONE:
                break
            yield item
    finally:
        await graph_task


def build_orchestrator_graph(http, cards, model=None, model_call_limit: int = 5, emit=None):
    """discover된 카드마다 원격 호출 tool을 만들고 종합 미들웨어를 붙여 ReAct 그래프를 만든다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    tools = [build_agent_tool(http, name, card, call_agent_fn=call_agent, emit=emit)
             for name, card in cards.items()]
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        middleware=[StepLimitSynthesisMiddleware(model_call_limit)],
    )
```

설계 노트:
- ReAct chunk와 서브 이벤트가 **같은 큐**로 모인다. agent_tool의 `emit`이 곧 `sub_event_queue.put_nowait`이므로, tool 실행 중 발생한 서브 이벤트는 그 tool 결과 chunk보다 먼저 큐에 들어가 시간순이 보장된다.
- `to_progress_event`로 만든 로컬 이벤트도 같은 큐에 넣어 단일 소비 루프로 통일한다.
- `_STREAM_DONE` sentinel로 종료, `finally`에서 `graph_task`를 await해 누수 방지. 큐에 남은 항목은 sentinel 이전에 모두 소비된다(sentinel은 항상 마지막에 put).

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_orchestrate.py -v`
Expected: PASS (신규 1개 + 기존 4개)

- [ ] **Step 5: 커밋**

```bash
git add orchestrator/orchestrate.py tests/test_orchestrate.py
git commit -m "feat: ReAct chunk와 서브 에이전트 이벤트를 큐로 병합해 스트리밍"
```

---

## Task 8: 전체 회귀 + SSE end-to-end 확인

전체 테스트 스위트를 돌려 회귀를 확인하고, SSE payload에 `path`가 한글 비이스케이프로 실리는지 마지막으로 검증한다.

**Files:**
- Test: 전체 `tests/`

**Interfaces:**
- Consumes: 모든 이전 태스크.

- [ ] **Step 1: SSE에 서브 path 이벤트가 실리는지 end-to-end 테스트 추가**

`tests/test_orchestrator_server.py`에 추가:

```python
def test_post_run_streams_sub_agent_path_event():
    # given — path가 실린 서브 tool_call 이벤트를 내는 fake run_stream
    from orchestrator.events import ProgressEvent

    async def fake_run_stream(task, **kwargs):
        yield ProgressEvent(type="tool_call", agent="tavily", input="양자컴퓨팅", path=["research"])
        yield final_event(content="완료", truncated=False)

    client = TestClient(build_app(run_stream=fake_run_stream))

    # when
    response = client.post("/run", json={"task": "hello"})

    # then — path가 payload에 실리고 한글이 이스케이프되지 않는다
    assert "\\u" not in response.text
    payloads = [json.loads(block[len("data: "):])
                for block in response.text.split("\r\n\r\n") if block]
    assert payloads[0] == {"type": "tool_call", "agent": "tavily", "input": "양자컴퓨팅", "path": ["research"]}
    assert payloads[1]["content"] == "완료"
```

- [ ] **Step 2: 신규 테스트 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_orchestrator_server.py -v`
Expected: PASS

- [ ] **Step 3: 전체 스위트 실행**

Run: `source .venv/bin/activate && pytest -v`
Expected: PASS (전체). 실패가 있으면 해당 태스크로 돌아가 수정.

- [ ] **Step 4: 커밋**

```bash
git add tests/test_orchestrator_server.py
git commit -m "test: 서브 에이전트 path 이벤트의 SSE end-to-end 검증 추가"
```

---

## Self-Review 결과

**Spec coverage:**
- 결정 1(툴 단위) → Task 2/4 (tool_call/tool_result 추출·발행). ✓
- 결정 2(path 계층) → Task 1(필드), Task 6(부여), Task 7(병합). ✓
- 결정 3(A2A 네이티브 transport) → Task 4(status_update 발행), Task 5(streaming 수신). ✓
- 결정 4(metadata dict 인코딩) → Task 4(`step_metadata`), Task 5(`extract_progress_metadata`). ✓
- 결정 5(스트리밍 전면 전환) → Task 4(astream만), Task 5(streaming=True만). ✓
- 에러 처리(spec §5): graph 실패→Task 4 `failed`, 비표준 metadata→Task 5 관대 처리, 콜백 격리→Task 6 try/except, 병합 종료→Task 7 sentinel+finally. ✓
- 테스트(spec §6): Task별 테스트 + Task 8 회귀. ✓

**Placeholder scan:** TBD/TODO/"적절히 처리" 없음. 모든 코드 스텝에 전체 코드 포함. ✓

**Type consistency:**
- `GraphStep`(kind/agent/input/output/content/truncated) — Task 2 정의, Task 3/4에서 동일 필드명 사용. ✓
- `extract_graph_step` — Task 2 정의, Task 3/4 소비. ✓
- `call_agent(http, card, text, on_event=None)` — Task 5 정의, Task 6/7 가짜 시그니처 일치. ✓
- `extract_progress_metadata` — Task 5 정의·소비. ✓
- `build_agent_tool(..., emit=None)` — Task 6 정의, Task 7 `emit=sub_event_queue.put_nowait` 연결. ✓
- `step_to_progress_event`/`sub_progress_event` — Task 3/6에서 각각 정의, path 부여 일관. ✓
- `metadata["kind"]` 접근: protobuf Struct는 `dict()` 변환 후 사용(Task 5에서 `dict(message.metadata)`). ✓

이슈 없음.
