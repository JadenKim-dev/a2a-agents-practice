# 오케스트레이터 SSE 스트리밍 서버 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 오케스트레이터를 CLI 단발 실행에서 SSE 스트리밍 HTTP 서버로 전환하고, ReAct 진행 상황을 스텝 단위로 흘리며, step limit 도달 시 그래프 내부에서 강제 종합 답변을 만든다.

**Architecture:** starlette `POST /run`이 `run_task_stream`(async generator)을 구독해 `ProgressEvent`를 SSE로 직렬화한다. `run_task_stream`은 `graph.astream(stream_mode="updates")`의 chunk를 `events.to_progress_event`로 변환해 yield한다. `StepLimitSynthesisMiddleware`가 모델 호출 한도 직전 스텝에서 tools를 비우고 종합을 강제해 `GraphRecursionError` 없이 best-effort 답변을 만든다.

**Tech Stack:** Python 3.11+, langchain 1.3.x (`create_agent` + middleware), langgraph 1.2.x, starlette 1.3.x, uvicorn, httpx, pytest/pytest-asyncio.

## Global Constraints

- langchain `create_agent`는 미들웨어 기반(1.x). 옛 `create_react_agent`의 `remaining_steps`/`pre_model_hook`은 사용 불가.
- `request.override(tools=[], system_prompt=...)`로만 요청을 변경한다 (직접 속성 대입은 deprecated).
- `await handler(request)`는 `ModelResponse`를 반환하며 실제 AIMessage는 `response.result[0]`.
- `astream(stream_mode="updates")` chunk는 `{node_name: {"messages": [...]}}`, 노드명은 `"model"`/`"tools"`.
- 비동기 실행 경로이므로 미들웨어는 `awrap_model_call`을 구현한다 (동기 `wrap_model_call`은 async에서 호출되지 않음).
- docstring은 한글 명사구가 아닌 한글 declarative("~한다") 형태로 작성 (CLAUDE.md).
- 선언 순서: static→instance, field→method, public→private, caller→callee (CLAUDE.md).
- 테스트: given/when/then 주석, `it` 블록 내 리터럴 입력, per-field assert, 동작 기반 케이스명.
- 새 의존성 추가 금지. starlette는 `a2a-sdk[http-server]`가 이미 제공.

---

### Task 1: `orchestrator/events.py` — 진행 이벤트 도메인 타입과 변환기

**Files:**
- Create: `orchestrator/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: langchain-core 메시지(`AIMessage`, `ToolMessage`), `message_content_to_text`(`orchestrator/llm.py`).
- Produces:
  - `ProgressEvent` — `dataclass`, 필드 `type: str`, `agent: str | None = None`, `input: str | None = None`, `output: str | None = None`, `content: str | None = None`, `truncated: bool = False`, `message: str | None = None`.
  - `tool_call_event(agent: str, input: str) -> ProgressEvent`
  - `tool_result_event(agent: str, output: str) -> ProgressEvent`
  - `final_event(content: str, truncated: bool) -> ProgressEvent`
  - `error_event(message: str) -> ProgressEvent`
  - `to_progress_event(chunk: dict) -> ProgressEvent | None` — astream `updates` chunk 하나를 이벤트로 변환, 매핑 대상 없으면 `None`. 한 chunk에 여러 메시지가 있어도 첫 매핑 가능한 메시지 하나만 변환한다(스텝 단위 1 chunk = 최대 1 이벤트로 단순화).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.events import (
    ProgressEvent,
    to_progress_event,
    final_event,
    error_event,
)


def test_to_progress_event_maps_tool_call_to_tool_call_event():
    # given — model 노드가 tool_calls를 가진 AIMessage를 낸 chunk
    chunk = {
        "model": {
            "messages": [
                AIMessage(content="", tool_calls=[
                    {"name": "research", "args": {"input": "quantum computing"},
                     "id": "c1", "type": "tool_call"}])
            ]
        }
    }

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "tool_call"
    assert event.agent == "research"
    assert event.input == "quantum computing"


def test_to_progress_event_maps_tool_message_to_tool_result_event():
    # given — tools 노드가 ToolMessage를 낸 chunk
    chunk = {
        "tools": {
            "messages": [
                ToolMessage(content="OUT[quantum computing]", name="research",
                            tool_call_id="c1")
            ]
        }
    }

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "tool_result"
    assert event.agent == "research"
    assert event.output == "OUT[quantum computing]"


def test_to_progress_event_maps_plain_ai_message_to_final_event():
    # given — model 노드가 tool_calls 없는 최종 AIMessage를 낸 chunk
    chunk = {"model": {"messages": [AIMessage(content="final synthesized answer")]}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "final"
    assert event.content == "final synthesized answer"
    assert event.truncated is False


def test_to_progress_event_reads_truncated_marking_from_response_metadata():
    # given — 강제 종합으로 truncated 마킹이 붙은 최종 AIMessage
    message = AIMessage(content="partial best-effort answer")
    message.response_metadata = {"truncated": True}
    chunk = {"model": {"messages": [message]}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "final"
    assert event.truncated is True


def test_to_progress_event_returns_none_for_unmappable_chunk():
    # given — messages가 비어 매핑할 대상이 없는 chunk
    chunk = {"model": {"messages": []}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.events'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/events.py
"""ReAct 스트림 chunk를 사용자에게 노출할 진행 이벤트로 변환한다."""
from dataclasses import dataclass

from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.llm import message_content_to_text


@dataclass
class ProgressEvent:
    """오케스트레이션 진행의 한 스텝을 표현한다."""
    type: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool = False
    message: str | None = None


def to_progress_event(chunk: dict) -> ProgressEvent | None:
    """astream updates chunk 하나를 진행 이벤트로 변환한다. 매핑 대상이 없으면 None을 반환한다."""
    for update in chunk.values():
        for message in update.get("messages", []):
            event = _message_to_event(message)
            if event is not None:
                return event
    return None


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


def _message_to_event(message) -> ProgressEvent | None:
    if isinstance(message, AIMessage) and message.tool_calls:
        call = message.tool_calls[0]
        return tool_call_event(agent=call["name"], input=call["args"].get("input", ""))
    if isinstance(message, ToolMessage):
        return tool_result_event(agent=message.name, output=message_content_to_text(message))
    if isinstance(message, AIMessage):
        truncated = bool(message.response_metadata.get("truncated", False))
        return final_event(content=message_content_to_text(message), truncated=truncated)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_events.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/events.py tests/test_events.py
git commit -m "feat: 진행 이벤트 도메인 타입과 stream chunk 변환기 추가"
```

---

### Task 2: `orchestrator/middleware.py` — step limit 강제 종합 미들웨어

**Files:**
- Create: `orchestrator/middleware.py`
- Test: `tests/test_middleware.py`

**Interfaces:**
- Consumes: `AgentMiddleware`, `ModelRequest`(`langchain.agents.middleware`), `ModelResponse`(`await handler` 반환 타입).
- Produces:
  - `StepLimitSynthesisMiddleware(model_call_limit: int)` — `AgentMiddleware` 서브클래스.
    `awrap_model_call(request, handler)`에서 instance 카운터를 증가시키고, `model_call_limit - 1` 번째 호출(0-기반으로 카운터가 `limit - 1`에 도달)이면 `request.override(tools=[], system_prompt=SYNTHESIS_PROMPT)`로 종합을 강제하고 결과 AIMessage(`response.result[0]`)에 `response_metadata["truncated"]=True`를 단다.
  - `SYNTHESIS_PROMPT: str` — 종합 지시 시스템 프롬프트 상수.

**참고(검증된 동작):** `await handler(request)`는 `ModelResponse`를 반환하고 실제 AIMessage는 `response.result[0]`. instance 카운터는 단일 run 동안만 유효하면 충분(PoC, multi-run 영속 불필요).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_middleware.py
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from langchain.agents.middleware import ModelRequest, ModelResponse

from orchestrator.middleware import StepLimitSynthesisMiddleware, SYNTHESIS_PROMPT


def _dummy_tool():
    def run(input: str) -> str:
        return input
    return StructuredTool.from_function(func=run, name="research", description="d")


def _request_with_tools():
    # override가 새 ModelRequest를 dataclasses.replace로 만들므로, 최소 필드만 채운 진짜 ModelRequest를 쓴다.
    return ModelRequest(
        model=None,
        messages=[],
        system_message=None,
        tool_choice=None,
        tools=[_dummy_tool()],
        response_format=None,
        state={"messages": []},
        runtime=None,
        model_settings={},
    )


async def test_keeps_tools_before_limit_is_reached():
    # given — 한도 5, 첫 호출. handler는 받은 request를 기록하고 ModelResponse를 돌려준다.
    middleware = StepLimitSynthesisMiddleware(model_call_limit=5)
    seen = {}

    async def handler(request):
        seen["tools"] = request.tools
        return ModelResponse(result=[AIMessage(content="ok")], structured_response=None)

    # when
    await middleware.awrap_model_call(_request_with_tools(), handler)

    # then
    assert len(seen["tools"]) == 1


async def test_strips_tools_and_injects_synthesis_prompt_on_final_step():
    # given — 한도 1이라 첫 호출이 곧 마지막. handler가 받은 request를 기록.
    middleware = StepLimitSynthesisMiddleware(model_call_limit=1)
    seen = {}

    async def handler(request):
        seen["tools"] = request.tools
        seen["system_prompt"] = request.system_prompt
        return ModelResponse(result=[AIMessage(content="best effort")], structured_response=None)

    # when
    response = await middleware.awrap_model_call(_request_with_tools(), handler)

    # then
    assert seen["tools"] == []
    assert seen["system_prompt"] == SYNTHESIS_PROMPT
    assert response.result[0].response_metadata["truncated"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.middleware'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/middleware.py
"""step limit 도달 직전에 도구를 제거하고 종합을 강제해 best-effort 답변을 만든다."""
from langchain.agents.middleware import AgentMiddleware

SYNTHESIS_PROMPT = (
    "You have reached the step budget and may not call any more tools. "
    "Using only the information gathered so far, write the best possible "
    "final answer to the user's task. Acknowledge briefly if it is incomplete."
)


class StepLimitSynthesisMiddleware(AgentMiddleware):
    """모델 호출이 한도에 도달하는 스텝에서 도구를 비우고 종합을 강제한다."""

    def __init__(self, model_call_limit: int):
        super().__init__()
        self._model_call_limit = model_call_limit
        self._call_count = 0

    async def awrap_model_call(self, request, handler):
        self._call_count += 1
        if self._call_count >= self._model_call_limit:
            request = request.override(tools=[], system_prompt=SYNTHESIS_PROMPT)
            response = await handler(request)
            message = response.result[0]
            message.response_metadata = {**message.response_metadata, "truncated": True}
            return response
        return await handler(request)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_middleware.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/middleware.py tests/test_middleware.py
git commit -m "feat: step limit 도달 시 도구 제거 후 종합을 강제하는 미들웨어 추가"
```

---

### Task 3: `orchestrator/orchestrate.py` — `run_task`를 `run_task_stream`으로 재작성

**Files:**
- Modify: `orchestrator/orchestrate.py` (전체 재작성)
- Modify: `tests/test_orchestrate.py` (단발 `run_task` 테스트 제거 → 스트리밍 테스트로 대체)

**Interfaces:**
- Consumes: `discover_agents`, `build_agent_tool`, `call_agent`, `to_progress_event`/`final_event`/`error_event`(Task 1), `StepLimitSynthesisMiddleware`(Task 2), `create_agent`.
- Produces:
  - `async def run_task_stream(task: str, model=None, model_call_limit: int = 5, recursion_limit: int = 25) -> AsyncIterator[ProgressEvent]` — async generator. discover 0개면 `final_event("No agents available.", truncated=False)` 하나만 yield. 아니면 `graph.astream(stream_mode="updates")`를 순회하며 `to_progress_event`로 변환해 yield, 도중 예외는 `error_event`로 yield.
  - `build_orchestrator_graph(http, cards, model=None, model_call_limit: int = 5)` — 미들웨어를 포함해 그래프를 만든다.
- 제거: `run_task`(단발), 기존 `GraphRecursionError` try/except.

**참고:** `recursion_limit`은 미들웨어 한도(`model_call_limit`)보다 넉넉한 안전망. 미들웨어가 종합을 강제하므로 정상 경로에서 `GraphRecursionError`는 발생하지 않는다.

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrate.py`를 아래로 교체한다 (기존 `test_run_task_*` 3개 제거, `test_extract_response_text_*`는 유지). `ToolCallingFakeModel`과 `_cards()`는 그대로 둔다.

```python
# tests/test_orchestrate.py
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

    async def fake_call_agent(http, card, text):
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
    types = [event.type for event in events]
    assert types == ["tool_call", "tool_result", "tool_call", "tool_result", "final"]
    assert events[0].agent == "research"
    assert events[0].input == "quantum computing"
    assert events[1].output == "OUT[quantum computing]"
    assert events[-1].content == "final synthesized answer"
    assert events[-1].truncated is False


async def test_run_task_stream_emits_truncated_final_event_when_step_limit_hit(monkeypatch):
    # given — LLM이 끝없이 research를 호출, model_call_limit=2로 강제 종합
    async def fake_discover(http):
        return _cards()
    monkeypatch.setattr("orchestrator.orchestrate.discover_agents", fake_discover)

    async def fake_call_agent(http, card, text):
        return "more"
    monkeypatch.setattr("orchestrator.orchestrate.call_agent", fake_call_agent)

    def endless_then_synthesis():
        # 처음엔 tool_call, 강제 종합 스텝(tools 비워짐)에서는 plain 답변을 낸다.
        yield AIMessage(content="", tool_calls=[
            {"name": "research", "args": {"input": "again"},
             "id": "c", "type": "tool_call"}])
        while True:
            yield AIMessage(content="best-effort partial answer")
    fake_model = ToolCallingFakeModel(messages=endless_then_synthesis())

    # when
    events = await _collect(run_task_stream(
        "loop forever", model=fake_model, model_call_limit=2, recursion_limit=25))

    # then
    assert events[-1].type == "final"
    assert events[-1].truncated is True
    assert events[-1].content == "best-effort partial answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_orchestrate.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_task_stream'`

- [ ] **Step 3: Write minimal implementation**

`orchestrator/orchestrate.py`를 아래로 전체 교체한다.

```python
# orchestrator/orchestrate.py
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


async def run_task_stream(
    task: str,
    model=None,
    model_call_limit: int = 5,
    recursion_limit: int = 25,
) -> AsyncIterator[ProgressEvent]:
    """Task에 대해 discover→build→ReAct astream을 수행하며 진행 이벤트를 yield한다."""
    async with httpx.AsyncClient() as http:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_orchestrate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrate.py tests/test_orchestrate.py
git commit -m "feat: run_task를 진행 이벤트를 흘리는 run_task_stream으로 재작성"
```

---

### Task 4: `orchestrator/server.py` — SSE 스트리밍 starlette 앱

**Files:**
- Create: `orchestrator/server.py`
- Test: `tests/test_orchestrator_server.py`

**Interfaces:**
- Consumes: `run_task_stream`(Task 3), `ProgressEvent`(Task 1), starlette `Starlette`/`Route`/`StreamingResponse`/`Request`.
- Produces:
  - `def build_app(run_stream=run_task_stream) -> Starlette` — `POST /run` 라우트 하나. body의 `task`를 읽어 `run_stream(task)`를 SSE로 직렬화. `run_stream`을 주입 가능하게 해 테스트에서 fake를 넣는다.
  - `def event_to_sse(event: ProgressEvent) -> str` — `ProgressEvent`를 `data: <json>\n\n` 문자열로 직렬화 (None 필드는 제외).

**참고(검증됨):** starlette `StreamingResponse(async_gen, media_type="text/event-stream")` 동작. `TestClient`는 스트림 body를 `response.text`로 전부 버퍼링.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_server.py
import json

from starlette.testclient import TestClient

from orchestrator.events import tool_call_event, final_event
from orchestrator.server import build_app, event_to_sse


def test_event_to_sse_serializes_only_present_fields():
    # given — agent와 input만 있는 tool_call 이벤트
    event = tool_call_event(agent="research", input="quantum")

    # when
    line = event_to_sse(event)

    # then
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    payload = json.loads(line[len("data: "):].strip())
    assert payload == {"type": "tool_call", "agent": "research", "input": "quantum"}


def test_post_run_streams_events_as_sse():
    # given — 두 이벤트를 내는 fake run_stream을 주입한 앱
    async def fake_run_stream(task, **kwargs):
        yield tool_call_event(agent="research", input=task)
        yield final_event(content="done", truncated=False)

    client = TestClient(build_app(run_stream=fake_run_stream))

    # when
    response = client.post("/run", json={"task": "hello"})

    # then
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = [b for b in response.text.split("\n\n") if b]
    first = json.loads(blocks[0][len("data: "):])
    last = json.loads(blocks[1][len("data: "):])
    assert first == {"type": "tool_call", "agent": "research", "input": "hello"}
    assert last == {"type": "final", "content": "done", "truncated": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_orchestrator_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.server'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/server.py
"""오케스트레이션 진행을 SSE로 스트리밍하는 일반 HTTP 서버를 구성한다."""
import json
from dataclasses import asdict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from orchestrator.events import ProgressEvent
from orchestrator.orchestrate import run_task_stream


def build_app(run_stream=run_task_stream) -> Starlette:
    """POST /run에서 task를 받아 진행 이벤트를 SSE로 흘리는 앱을 만든다."""
    async def run(request: Request) -> StreamingResponse:
        body = await request.json()
        task = body["task"]

        async def event_stream():
            async for event in run_stream(task):
                yield event_to_sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return Starlette(routes=[Route("/run", run, methods=["POST"])])


def event_to_sse(event: ProgressEvent) -> str:
    """ProgressEvent를 None 필드를 제외한 data: <json> SSE 라인으로 직렬화한다."""
    payload = {key: value for key, value in asdict(event).items() if value is not None}
    return f"data: {json.dumps(payload)}\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_orchestrator_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/server.py tests/test_orchestrator_server.py
git commit -m "feat: 진행 이벤트를 SSE로 스트리밍하는 오케스트레이터 서버 추가"
```

---

### Task 5: `orchestrator/__main__.py` — CLI 제거, uvicorn 서버 기동

**Files:**
- Modify: `orchestrator/__main__.py` (전체 재작성)

**Interfaces:**
- Consumes: `build_app`(Task 4), `uvicorn`, `load_dotenv`.
- Produces: `main()` — `python -m orchestrator` 실행 시 `127.0.0.1:9000`에 SSE 서버를 기동.

**참고:** 이 Task는 진입점 배선이라 자동화 단위 테스트 대신 수동 기동 확인으로 검증한다 (에이전트 `__main__.py`들도 단위 테스트 없이 기동 코드만 둔 기존 패턴과 일치).

- [ ] **Step 1: `__main__.py`를 재작성**

```python
# orchestrator/__main__.py
"""오케스트레이터 서버 진입점: python -m orchestrator → :9000 SSE 서버."""
import uvicorn
from dotenv import load_dotenv

from orchestrator.server import build_app

load_dotenv()


def main() -> None:
    uvicorn.run(build_app(), host="127.0.0.1", port=9000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: import 무결성 확인 (기동 코드 자체는 블로킹이므로 import만 검증)**

Run: `.venv/bin/python -c "import orchestrator.__main__; print('import ok')"`
Expected: `import ok` (예외 없이)

- [ ] **Step 3: 서버 수동 기동 확인 (선택, 환경에 에이전트가 떠 있지 않아도 기동 자체는 확인 가능)**

Run: `.venv/bin/python -m orchestrator` 를 백그라운드로 띄운 뒤 다른 셸에서:
```bash
curl -N -X POST http://127.0.0.1:9000/run -H 'content-type: application/json' -d '{"task":"hi"}'
```
Expected: 에이전트가 discover 안 되면 `data: {"type": "final", "content": "No agents available.", "truncated": false}` 한 줄이 SSE로 오고 스트림 종료. (에이전트가 떠 있으면 tool_call/tool_result/final 이벤트가 순차 도착.) 확인 후 서버 프로세스 종료.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/__main__.py
git commit -m "feat: 오케스트레이터 진입점을 CLI에서 SSE 서버 기동으로 전환"
```

---

### Task 6: README 업데이트 — 서버 실행법 반영

**Files:**
- Modify: `README.md` (오케스트레이터 실행 섹션)

**Interfaces:** 없음 (문서).

**참고:** 현재 README는 `python -m orchestrator "<task>"` CLI 사용법을 안내한다. 이를 서버 기동 + curl SSE 예시로 교체한다.

- [ ] **Step 1: README의 오케스트레이터 실행 부분을 확인**

Run: `.venv/bin/python -c "print(open('README.md').read())"`
(또는 에디터로 열어) `python -m orchestrator "<task>"` 표기 위치를 찾는다.

- [ ] **Step 2: 해당 섹션을 서버 실행법으로 교체**

오케스트레이터 실행 안내를 아래 취지로 바꾼다 (정확한 주변 문구는 기존 README 형식에 맞춘다):

```markdown
오케스트레이터를 SSE 서버로 기동:

    python -m orchestrator   # http://127.0.0.1:9000

진행 상황을 SSE로 받으며 task 실행:

    curl -N -X POST http://127.0.0.1:9000/run \
      -H 'content-type: application/json' \
      -d '{"task":"양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"}'

각 줄은 `data: {...}` SSE 이벤트다. `type`은 `tool_call`(에이전트 호출 시작),
`tool_result`(결과 관찰), `final`(최종 답변; `truncated`가 true면 step limit으로
강제 종합된 부분 답변), `error`(스트림 중 예외) 중 하나다.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: 오케스트레이터 실행법을 SSE 서버 기준으로 갱신"
```

---

### Task 7: 전체 회귀 검증

**Files:** 없음 (검증 전용).

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS. 특히 `test_events.py`, `test_middleware.py`, `test_orchestrate.py`, `test_orchestrator_server.py`가 통과하고, 기존 `test_agent_tool.py`/`test_agent_card.py`/`test_server.py` 등이 깨지지 않음.

- [ ] **Step 2: 더 이상 참조되지 않는 심볼 점검**

Run: `grep -rn "run_task\b" orchestrator tests` (단발 `run_task` 잔존 참조 확인)
Expected: `run_task_stream`만 매칭되고 단발 `run_task(` 호출은 남아 있지 않음. 남아 있으면 해당 위치를 수정.

- [ ] **Step 3: (이상 없으면) 검증 완료. 별도 커밋 불필요.**

---

## Self-Review

**1. Spec coverage:**
- 진행 상황 SSE 스트리밍 → Task 1(이벤트 변환) + Task 3(astream) + Task 4(SSE 서버). ✓
- 서버 형식 노출(일반 HTTP) → Task 4 + Task 5. ✓
- step limit graceful degradation(그래프 내부 통합) → Task 2(미들웨어) + Task 3(배선). ✓
- CLI 제거 → Task 5. ✓
- `error` 이벤트 타입 → Task 1(정의) + Task 3(yield). ✓
- `truncated` 플래그 → Task 1(reads response_metadata) + Task 2(marks). ✓
- 테스트 전략 표의 모든 행 → Task 1/2/3/4 테스트로 커버. ✓
- README 갱신(CLI 제거 반영) → Task 6. ✓

**2. Placeholder scan:** "TBD"/"적절히 처리" 등 없음. 모든 코드 스텝에 실제 코드 포함. ✓

**3. Type consistency:**
- `ProgressEvent` 필드(`type/agent/input/output/content/truncated/message`)가 Task 1 정의와 Task 3/4 사용에서 일치. ✓
- `run_task_stream(task, model, model_call_limit, recursion_limit)` 시그니처가 Task 3 정의와 Task 4 호출(`run_stream(task)`)·테스트에서 일치. ✓
- `StepLimitSynthesisMiddleware(model_call_limit)` 생성자가 Task 2 정의와 Task 3 사용에서 일치. ✓
- `await handler(request)` → `ModelResponse`, `.result[0]` AIMessage 접근이 Task 2 코드·테스트에서 일치(검증된 API). ✓
- astream chunk 형태 `{node: {"messages":[...]}}`가 Task 1 변환기·테스트와 일치(검증됨). ✓
