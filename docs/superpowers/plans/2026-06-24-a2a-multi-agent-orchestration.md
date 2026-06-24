# A2A 멀티 에이전트 오케스트레이션 PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Research/Summarizer 에이전트를 독립 A2A 서버로 띄우고, LLM 동적 라우팅 오케스트레이터가 A2A 프로토콜로 이들을 조합해 "리서치 → 요약" 과업을 끝까지 수행하는 동작 PoC를 만든다.

**Architecture:** 각 에이전트는 LangGraph(`langchain.agents.create_agent`, OpenAI `gpt-4o-mini`) 두뇌를 가진 독립 HTTP 서버로, 자신을 protobuf `AgentCard`로 노출한다. 공통 어댑터(`common/`)가 LangGraph 그래프를 A2A `AgentExecutor`로 감싸고 서버를 조립한다. 오케스트레이터는 A2A 클라이언트로서 카드를 discovery → LLM이 호출 계획 수립 → 각 에이전트에 A2A 메시지 위임 → 결과 종합한다.

**Tech Stack:** Python, `a2a-sdk` 1.1.0 (protobuf 기반 API), `langgraph` 1.x, `langchain-openai`, `langchain-tavily`, `uvicorn`, `httpx`, `pytest`.

## Global Constraints

- **a2a-sdk 버전 1.1.0 고정.** 이 버전은 protobuf 타입 기반이며 0.3.x와 API가 다르다. 아래 검증된 패턴만 사용한다:
  - `AgentCard`는 protobuf. URL은 `supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=...)]`로 넣는다 (`url=` 최상위 인자 없음).
  - Executor에서 `context.current_task`가 None이면 `new_task_from_user_message(context.message)`로 Task를 만들어 `event_queue.enqueue_event(task)`를 **먼저** 호출한 뒤 `TaskUpdater`를 쓴다.
  - 서버 조립: `DefaultRequestHandler(agent_executor, task_store, agent_card)` → `create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")` → `Starlette(routes=...)`.
  - 클라이언트: `A2ACardResolver(httpx_client, base_url).get_agent_card()` → `ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)` → `async for ev in client.send_message(SendMessageRequest(message=...))`.
- **LLM 모델: OpenAI `gpt-4o-mini`** (모든 에이전트·오케스트레이터 공통). 환경변수 `OPENAI_API_KEY`.
- **검색 툴: Tavily** (`langchain_tavily.TavilySearch`). 환경변수 `TAVILY_API_KEY`.
- **포트:** Research `9001`, Summarizer `9002`.
- **테스트는 LLM/Tavily 호출을 가짜로 대체**해 결정론적으로 만든다. 실제 OpenAI/Tavily 호출은 수동 E2E에서만.
- **패키지 버전 핀 (pyproject):** `a2a-sdk[http-server]==1.1.0`, `langgraph>=1.2,<2`, `langchain-openai>=1.3,<2`, `langchain-tavily>=0.2,<0.3`, `uvicorn>=0.49`, `httpx>=0.28`. 개발 의존성: `pytest>=8`, `pytest-asyncio>=0.24`, `anyio`.
- **CLAUDE.md 준수:** 약어 금지·서술적 이름, given/when/then 주석을 각 테스트에 명시, 입력 리터럴을 `it` 블록 안에 둔다.

## File Structure

```
a2a_agents/
├── pyproject.toml
├── .env.example
├── common/
│   ├── __init__.py
│   ├── agent_card.py          # build_agent_card() — protobuf AgentCard 생성 헬퍼
│   ├── langgraph_executor.py  # LangGraphExecutor: LangGraph graph → A2A AgentExecutor
│   └── server.py              # run_agent_server() — 카드+executor → Starlette+uvicorn
├── agents/
│   ├── __init__.py
│   ├── research/
│   │   ├── __init__.py
│   │   ├── graph.py           # build_research_graph()
│   │   ├── card.py            # RESEARCH_CARD
│   │   └── __main__.py        # python -m agents.research → :9001
│   └── summarizer/
│       ├── __init__.py
│       ├── graph.py           # build_summarizer_graph()
│       ├── card.py            # SUMMARIZER_CARD
│       └── __main__.py        # python -m agents.summarizer → :9002
├── orchestrator/
│   ├── __init__.py
│   ├── registry.py            # AGENT_URLS, discover_agents()
│   ├── client.py              # call_agent() — 원격 에이전트에 메시지 전송, 텍스트 회수
│   ├── planner.py             # plan_calls() — LLM이 호출 계획 산출 + 검증
│   ├── orchestrate.py         # run_task() — discover→plan→execute→synthesize
│   └── __main__.py            # CLI 진입점
├── scripts/
│   └── run_all.sh
└── tests/
    ├── __init__.py
    ├── test_langgraph_executor.py
    ├── test_research_graph.py
    ├── test_summarizer_graph.py
    ├── test_planner.py
    └── test_orchestrate.py
```

---

## Task 1: 프로젝트 스캐폴딩 & 의존성

**Files:**
- Create: `pyproject.toml`, `.env.example`, `common/__init__.py`, `agents/__init__.py`, `agents/research/__init__.py`, `agents/summarizer/__init__.py`, `orchestrator/__init__.py`, `tests/__init__.py`

**Interfaces:**
- Consumes: 없음 (최초 태스크)
- Produces: 설치 가능한 패키지 + 의존성. 이후 모든 태스크가 `pytest`로 실행됨.

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[project]
name = "a2a-agents"
version = "0.1.0"
description = "A2A multi-agent orchestration PoC"
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk[http-server]==1.1.0",
    "langgraph>=1.2,<2",
    "langchain-openai>=1.3,<2",
    "langchain-tavily>=0.2,<0.3",
    "uvicorn>=0.49",
    "httpx>=0.28",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "anyio>=4",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["common", "agents", "agents.research", "agents.summarizer", "orchestrator"]
```

- [ ] **Step 2: `.env.example` 작성**

```bash
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

- [ ] **Step 3: 빈 `__init__.py` 6개 생성**

`common/__init__.py`, `agents/__init__.py`, `agents/research/__init__.py`, `agents/summarizer/__init__.py`, `orchestrator/__init__.py`, `tests/__init__.py` — 모두 빈 파일.

- [ ] **Step 4: 설치 & 검증**

Run: `pip install -e ".[dev]"`
Expected: 성공. 이어서
Run: `python -c "import a2a, langgraph, langchain_openai, langchain_tavily; from langchain.agents import create_agent; from a2a.server.routes import create_jsonrpc_routes; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example common agents orchestrator tests
git commit -m "chore: 프로젝트 스캐폴딩 및 의존성 설정"
```

---

## Task 2: Agent Card 빌더 (`common/agent_card.py`)

**Files:**
- Create: `common/agent_card.py`
- Test: `tests/test_langgraph_executor.py` (Task 3에서 함께 작성하므로 여기서는 인라인 검증)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `build_agent_card(name: str, description: str, url: str, skill_id: str, skill_name: str, skill_description: str, skill_tags: list[str]) -> a2a.types.AgentCard`
  - 반환 카드는 `supported_interfaces`에 JSONRPC URL 1개, `capabilities.streaming=False`, `default_input_modes=["text"]`, `default_output_modes=["text"]`, `skills` 1개를 가진다.

- [ ] **Step 1: 실패하는 검증 스크립트 작성 (임시)**

`tests/test_agent_card.py` 생성:

```python
from common.agent_card import build_agent_card


def test_agent_card_url_is_in_supported_interfaces():
    # given
    name = "research"
    url = "http://127.0.0.1:9001/"

    # when
    card = build_agent_card(
        name=name,
        description="Researches topics",
        url=url,
        skill_id="research",
        skill_name="Research",
        skill_description="Find information on a topic",
        skill_tags=["research"],
    )

    # then
    assert card.name == name
    assert len(card.supported_interfaces) == 1
    assert card.supported_interfaces[0].url == url
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert len(card.skills) == 1
    assert card.skills[0].id == "research"
    assert card.default_input_modes == ["text"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_agent_card.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.agent_card'`

- [ ] **Step 3: `common/agent_card.py` 구현**

```python
"""A2A AgentCard(protobuf) 생성 책임."""
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill


def build_agent_card(
    name: str,
    description: str,
    url: str,
    skill_id: str,
    skill_name: str,
    skill_description: str,
    skill_tags: list[str],
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url)
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=skill_description,
                tags=skill_tags,
            )
        ],
    )
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_agent_card.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common/agent_card.py tests/test_agent_card.py
git commit -m "feat: A2A AgentCard 빌더 추가"
```

---

## Task 3: LangGraph → A2A Executor 어댑터 (`common/langgraph_executor.py`)

**Files:**
- Create: `common/langgraph_executor.py`
- Test: `tests/test_langgraph_executor.py`

**Interfaces:**
- Consumes: 없음 (LangGraph 그래프는 호출 시 주입)
- Produces:
  - `class LangGraphExecutor(AgentExecutor)` — 생성자 `__init__(self, graph)`. `graph`는 `.ainvoke({"messages": [{"role": "user", "content": str}]})`를 지원하고 `{"messages": [...]}`를 반환하는 객체 (LangGraph `CompiledGraph` 또는 동일 인터페이스의 가짜).
  - `execute(context, event_queue)`는 Task를 enqueue하고 그래프 최종 메시지 텍스트를 `complete` 메시지로 반환.
  - 그래프가 예외를 던지면 Task를 `failed` 상태 + 에러 텍스트로 완료(서버 무중단).
  - 모듈 헬퍼 `extract_last_text(graph_result: dict) -> str` — 그래프 결과에서 마지막 메시지의 텍스트 추출.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from a2a.server.events import EventQueue
from a2a.server.agent_execution import RequestContext
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


async def _drain(event_queue):
    events = []
    while not event_queue.is_closed() and not event_queue.empty():
        events.append(await event_queue.dequeue_event(no_wait=True))
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
    context = RequestContext(request=request)
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
    context = RequestContext(request=request)
    event_queue = EventQueue()

    # when
    await executor.execute(context, event_queue)

    # then
    events = await _drain(event_queue)
    states = [ev.status.state for ev in events if getattr(ev, "status", None)]
    from a2a.types import TaskState
    assert TaskState.TASK_STATE_FAILED in states
```

> 참고: `RequestContext(request=request)` 생성자 인자는 구현 중 실제 시그니처와 다르면 조정한다. `RequestContext.message`/`current_task`/`task_id`/`context_id` 속성은 1.1.0에 존재함이 검증됨.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_langgraph_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.langgraph_executor'`

- [ ] **Step 3: `common/langgraph_executor.py` 구현**

```python
"""LangGraph 그래프를 A2A AgentExecutor로 변환하는 어댑터 책임."""
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.types import Part


def extract_last_text(graph_result: dict) -> str:
    messages = graph_result.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", last)
    return content if isinstance(content, str) else str(content)


class LangGraphExecutor(AgentExecutor):
    """주입된 LangGraph 그래프 하나를 실행해 A2A Task로 응답한다."""

    def __init__(self, graph):
        self._graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        user_text = context.get_user_input()
        try:
            result = await self._graph.ainvoke(
                {"messages": [{"role": "user", "content": user_text}]}
            )
        except Exception as error:  # noqa: BLE001 — 서버 무중단 보장
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[Part(text=f"agent error: {error}")]
                )
            )
            return
        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=extract_last_text(result))]
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is out of scope for the PoC")
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_langgraph_executor.py -v`
Expected: PASS (3 tests). 실패 시 `RequestContext`/`EventQueue` 실제 시그니처를 `python -c "import inspect; from a2a.server.agent_execution import RequestContext; print(inspect.signature(RequestContext.__init__))"`로 확인해 테스트 헬퍼만 조정한다(구현 로직은 검증됨).

- [ ] **Step 5: Commit**

```bash
git add common/langgraph_executor.py tests/test_langgraph_executor.py
git commit -m "feat: LangGraph 그래프를 A2A Executor로 변환하는 어댑터 추가"
```

---

## Task 4: 서버 조립 헬퍼 (`common/server.py`)

**Files:**
- Create: `common/server.py`
- Test: `tests/test_langgraph_executor.py`에 서버 빌드 검증 1개 추가

**Interfaces:**
- Consumes: `LangGraphExecutor` (Task 3), `AgentCard` (Task 2)
- Produces:
  - `build_starlette_app(card: AgentCard, executor: AgentExecutor) -> starlette.applications.Starlette`
  - `run_agent_server(card: AgentCard, executor: AgentExecutor, host: str, port: int) -> None` — uvicorn 블로킹 실행.

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/test_server.py`)**

```python
from starlette.applications import Starlette

from common.agent_card import build_agent_card
from common.langgraph_executor import LangGraphExecutor


class FakeGraph:
    async def ainvoke(self, state):
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="ok")]}


def test_build_starlette_app_exposes_agent_card_route():
    # given
    card = build_agent_card(
        name="research",
        description="d",
        url="http://127.0.0.1:9001/",
        skill_id="research",
        skill_name="Research",
        skill_description="d",
        skill_tags=["research"],
    )
    executor = LangGraphExecutor(FakeGraph())

    # when
    from common.server import build_starlette_app
    app = build_starlette_app(card, executor)

    # then
    assert isinstance(app, Starlette)
    paths = {r.path for r in app.routes}
    assert "/.well-known/agent-card.json" in paths
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.server'`

- [ ] **Step 3: `common/server.py` 구현**

```python
"""AgentCard와 Executor로 A2A Starlette 앱을 조립하고 uvicorn으로 기동하는 책임."""
import uvicorn
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard


def build_starlette_app(card: AgentCard, executor: AgentExecutor) -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(
        handler, rpc_url="/"
    )
    return Starlette(routes=routes)


def run_agent_server(
    card: AgentCard, executor: AgentExecutor, host: str, port: int
) -> None:
    uvicorn.run(build_starlette_app(card, executor), host=host, port=port)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_server.py -v`
Expected: PASS. 실패 시 (route path 속성명 차이 등) `app.routes` 요소를 출력해 확인하고 테스트의 path 추출만 조정한다.

- [ ] **Step 5: Commit**

```bash
git add common/server.py tests/test_server.py
git commit -m "feat: A2A Starlette 서버 조립 헬퍼 추가"
```

---

## Task 5: Research 에이전트 (graph + card + main)

**Files:**
- Create: `agents/research/graph.py`, `agents/research/card.py`, `agents/research/__main__.py`
- Test: `tests/test_research_graph.py`

**Interfaces:**
- Consumes: `build_agent_card` (Task 2), `LangGraphExecutor`/`run_agent_server` (Task 3, 4)
- Produces:
  - `agents/research/graph.py`: `build_research_graph(model=None, search_tool=None)` — 인자 생략 시 `ChatOpenAI(model="gpt-4o-mini")` + `TavilySearch(max_results=3)`로 `langchain.agents.create_agent`를 만든다. 테스트는 가짜 model/tool 주입.
  - `agents/research/card.py`: `RESEARCH_CARD: AgentCard` (url `http://127.0.0.1:9001/`).
  - `agents/research/__main__.py`: `run_agent_server(RESEARCH_CARD, LangGraphExecutor(build_research_graph()), "127.0.0.1", 9001)`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agents.research.graph import build_research_graph


async def test_research_graph_returns_assistant_text_without_tool_calls():
    # given — 툴 호출 없이 바로 답하는 가짜 모델
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="quantum computing summary")]
    )

    def fake_search(query: str) -> str:
        return "irrelevant"

    graph = build_research_graph(model=fake_model, search_tool=fake_search)

    # when
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "research quantum computing"}]}
    )

    # then
    assert result["messages"][-1].content == "quantum computing summary"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_research_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.research.graph'`

- [ ] **Step 3: `agents/research/graph.py` 구현**

```python
"""웹 검색으로 주제를 조사하는 Research 에이전트의 LangGraph 그래프 책임."""
from langchain_core.tools import tool
from langchain.agents import create_agent

RESEARCH_SYSTEM_PROMPT = (
    "You are a research assistant. Use the search tool to gather facts about "
    "the user's topic, then write a concise factual briefing."
)


def build_research_graph(model=None, search_tool=None):
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    if search_tool is None:
        from langchain_tavily import TavilySearch
        search_tool = TavilySearch(max_results=3)
    elif not hasattr(search_tool, "name"):
        search_tool = tool(search_tool)
    return create_agent(
        model=model,
        tools=[search_tool],
        system_prompt=RESEARCH_SYSTEM_PROMPT,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_research_graph.py -v`
Expected: PASS

- [ ] **Step 5: `agents/research/card.py` 구현**

```python
"""Research 에이전트의 A2A AgentCard 책임."""
from common.agent_card import build_agent_card

RESEARCH_URL = "http://127.0.0.1:9001/"

RESEARCH_CARD = build_agent_card(
    name="research",
    description="Researches a topic using web search and returns a factual briefing.",
    url=RESEARCH_URL,
    skill_id="research",
    skill_name="Web Research",
    skill_description="Find current information on a topic and summarize the findings.",
    skill_tags=["research", "web-search"],
)
```

- [ ] **Step 6: `agents/research/__main__.py` 구현**

```python
"""Research 에이전트 서버 진입점: python -m agents.research → :9001."""
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import run_agent_server
from agents.research.card import RESEARCH_CARD
from agents.research.graph import build_research_graph

load_dotenv()


def main() -> None:
    executor = LangGraphExecutor(build_research_graph())
    run_agent_server(RESEARCH_CARD, executor, host="127.0.0.1", port=9001)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Commit**

```bash
git add agents/research tests/test_research_graph.py
git commit -m "feat: Research 에이전트(graph/card/server) 추가"
```

---

## Task 6: Summarizer 에이전트 (graph + card + main)

**Files:**
- Create: `agents/summarizer/graph.py`, `agents/summarizer/card.py`, `agents/summarizer/__main__.py`
- Test: `tests/test_summarizer_graph.py`

**Interfaces:**
- Consumes: `build_agent_card` (Task 2), `LangGraphExecutor`/`run_agent_server` (Task 3, 4)
- Produces:
  - `agents/summarizer/graph.py`: `build_summarizer_graph(model=None)` — 툴 없는 단순 그래프. 입력 텍스트를 요약. 테스트는 가짜 model 주입.
  - `agents/summarizer/card.py`: `SUMMARIZER_CARD: AgentCard` (url `http://127.0.0.1:9002/`).
  - `agents/summarizer/__main__.py`: `:9002` 기동.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agents.summarizer.graph import build_summarizer_graph


async def test_summarizer_graph_returns_summary_text():
    # given
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="short summary in three sentences")]
    )
    graph = build_summarizer_graph(model=fake_model)

    # when
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "long text to summarize ..."}]}
    )

    # then
    assert result["messages"][-1].content == "short summary in three sentences"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_summarizer_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.summarizer.graph'`

- [ ] **Step 3: `agents/summarizer/graph.py` 구현**

```python
"""입력 텍스트를 요약하는 Summarizer 에이전트의 LangGraph 그래프 책임."""
from langchain.agents import create_agent

SUMMARIZER_SYSTEM_PROMPT = (
    "You are a summarization assistant. Rewrite the user's text as a clear, "
    "faithful summary of about three paragraphs. Do not add new facts."
)


def build_summarizer_graph(model=None):
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    return create_agent(
        model=model,
        tools=[],
        system_prompt=SUMMARIZER_SYSTEM_PROMPT,
    )
```

> 참고: `create_agent`는 `tools=[]`도 허용한다(툴 없는 단일 LLM 노드). `from langchain.agents import create_agent` + 가짜 model + `tools=[]` 조합이 end-to-end로 검증됨. (구버전 `langgraph.prebuilt.create_react_agent`는 V2.0에서 제거 예정이라 사용하지 않는다.)

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_summarizer_graph.py -v`
Expected: PASS

- [ ] **Step 5: `agents/summarizer/card.py` 구현**

```python
"""Summarizer 에이전트의 A2A AgentCard 책임."""
from common.agent_card import build_agent_card

SUMMARIZER_URL = "http://127.0.0.1:9002/"

SUMMARIZER_CARD = build_agent_card(
    name="summarizer",
    description="Summarizes provided text into a concise multi-paragraph summary.",
    url=SUMMARIZER_URL,
    skill_id="summarize",
    skill_name="Summarize Text",
    skill_description="Condense provided text into a faithful short summary.",
    skill_tags=["summarize", "text"],
)
```

- [ ] **Step 6: `agents/summarizer/__main__.py` 구현**

```python
"""Summarizer 에이전트 서버 진입점: python -m agents.summarizer → :9002."""
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import run_agent_server
from agents.summarizer.card import SUMMARIZER_CARD
from agents.summarizer.graph import build_summarizer_graph

load_dotenv()


def main() -> None:
    executor = LangGraphExecutor(build_summarizer_graph())
    run_agent_server(SUMMARIZER_CARD, executor, host="127.0.0.1", port=9002)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Commit**

```bash
git add agents/summarizer tests/test_summarizer_graph.py
git commit -m "feat: Summarizer 에이전트(graph/card/server) 추가"
```

---

## Task 7: 오케스트레이터 — registry & client

**Files:**
- Create: `orchestrator/registry.py`, `orchestrator/client.py`
- Test: 실서버 왕복은 Task 10 수동 E2E에서. 여기서는 텍스트 추출 단위 테스트만 (`tests/test_orchestrate.py`에 추가).

**Interfaces:**
- Consumes: 없음 (A2A SDK 직접)
- Produces:
  - `orchestrator/registry.py`:
    - `AGENT_URLS: dict[str, str]` = `{"research": "http://127.0.0.1:9001", "summarizer": "http://127.0.0.1:9002"}`
    - `async def discover_agents(http: httpx.AsyncClient) -> dict[str, AgentCard]` — 각 URL에서 카드 resolve, 실패한 URL은 skip + 경고 출력.
  - `orchestrator/client.py`:
    - `async def call_agent(http: httpx.AsyncClient, card: AgentCard, text: str) -> str` — 카드로 클라이언트 생성, 메시지 전송, 응답에서 최종 텍스트 추출.
    - `def extract_response_text(stream_response) -> str` — `StreamResponse.payload` oneof에서 텍스트 추출.

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/test_orchestrate.py`)**

```python
from a2a.types import (
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskStatus,
    TaskState,
)

from orchestrator.client import extract_response_text


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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_orchestrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.client'`

- [ ] **Step 3: `orchestrator/registry.py` 구현**

```python
"""알려진 A2A 에이전트 URL 목록과 카드 discovery 책임."""
import httpx

from a2a.client import A2ACardResolver
from a2a.types import AgentCard

AGENT_URLS: dict[str, str] = {
    "research": "http://127.0.0.1:9001",
    "summarizer": "http://127.0.0.1:9002",
}


async def discover_agents(http: httpx.AsyncClient) -> dict[str, AgentCard]:
    cards: dict[str, AgentCard] = {}
    for name, url in AGENT_URLS.items():
        try:
            resolver = A2ACardResolver(http, base_url=url)
            cards[name] = await resolver.get_agent_card()
        except Exception as error:  # noqa: BLE001
            print(f"[discover] skip {name} ({url}): {error}")
    return cards
```

- [ ] **Step 4: `orchestrator/client.py` 구현**

```python
"""원격 A2A 에이전트에 메시지를 보내고 응답 텍스트를 회수하는 책임."""
import httpx

from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, StreamResponse


def extract_response_text(stream_response: StreamResponse) -> str:
    which = stream_response.WhichOneof("payload")
    if which == "task":
        status = stream_response.task.status
        if status.message and status.message.parts:
            return status.message.parts[0].text
    if which == "message":
        parts = stream_response.message.parts
        if parts:
            return parts[0].text
    if which == "status_update":
        message = stream_response.status_update.status.message
        if message and message.parts:
            return message.parts[0].text
    return ""


async def call_agent(http: httpx.AsyncClient, card: AgentCard, text: str) -> str:
    factory = ClientFactory(ClientConfig(httpx_client=http, streaming=False))
    client = factory.create(card)
    request = SendMessageRequest(
        message=Message(
            message_id="orchestrator-msg",
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )
    )
    final_text = ""
    async for event in client.send_message(request):
        extracted = extract_response_text(event)
        if extracted:
            final_text = extracted
    return final_text
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_orchestrate.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/registry.py orchestrator/client.py tests/test_orchestrate.py
git commit -m "feat: 오케스트레이터 registry 및 A2A 클라이언트 추가"
```

---

## Task 8: 오케스트레이터 — LLM 동적 라우팅 planner

**Files:**
- Create: `orchestrator/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `AgentCard` (discovery 결과)
- Produces:
  - `orchestrator/planner.py`:
    - `class PlannedCall(TypedDict)`: `{"agent": str, "input": str}`
    - `def cards_to_catalog(cards: dict[str, AgentCard]) -> str` — 카드들을 LLM 프롬프트용 텍스트로.
    - `async def plan_calls(task: str, cards: dict[str, AgentCard], model=None, max_calls: int = 5) -> list[PlannedCall]` — LLM이 JSON 호출 계획 산출. `cards`에 없는 agent 이름은 필터링. `max_calls` 초과분 절단. 테스트는 가짜 model 주입.
    - 계획 입력에 리터럴 `"{PREVIOUS_OUTPUT}"` 플레이스홀더를 허용 (execute 단계에서 직전 출력으로 치환).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from common.agent_card import build_agent_card
from orchestrator.planner import plan_calls, cards_to_catalog


def _cards():
    return {
        "research": build_agent_card(
            name="research", description="researches topics",
            url="http://127.0.0.1:9001/", skill_id="research",
            skill_name="Research", skill_description="web research",
            skill_tags=["research"],
        ),
        "summarizer": build_agent_card(
            name="summarizer", description="summarizes text",
            url="http://127.0.0.1:9002/", skill_id="summarize",
            skill_name="Summarize", skill_description="summarize text",
            skill_tags=["summarize"],
        ),
    }


def test_cards_to_catalog_lists_each_agent_name():
    # given
    cards = _cards()

    # when
    catalog = cards_to_catalog(cards)

    # then
    assert "research" in catalog
    assert "summarizer" in catalog


async def test_plan_calls_returns_parsed_plan():
    # given
    plan_json = json.dumps([
        {"agent": "research", "input": "quantum computing trends"},
        {"agent": "summarizer", "input": "{PREVIOUS_OUTPUT}"},
    ])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("research and summarize quantum computing",
                            _cards(), model=fake_model)

    # then
    assert plan == [
        {"agent": "research", "input": "quantum computing trends"},
        {"agent": "summarizer", "input": "{PREVIOUS_OUTPUT}"},
    ]


async def test_plan_calls_filters_unknown_agents():
    # given
    plan_json = json.dumps([
        {"agent": "nonexistent", "input": "x"},
        {"agent": "research", "input": "y"},
    ])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("task", _cards(), model=fake_model)

    # then
    assert plan == [{"agent": "research", "input": "y"}]


async def test_plan_calls_truncates_to_max_calls():
    # given
    plan_json = json.dumps([{"agent": "research", "input": str(i)} for i in range(10)])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("task", _cards(), model=fake_model, max_calls=3)

    # then
    assert len(plan) == 3
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.planner'`

- [ ] **Step 3: `orchestrator/planner.py` 구현**

```python
"""에이전트 카드를 근거로 LLM이 호출 계획을 산출하는 동적 라우팅 책임."""
import json
import re
from typing import TypedDict

from a2a.types import AgentCard

PREVIOUS_OUTPUT_PLACEHOLDER = "{PREVIOUS_OUTPUT}"

PLANNER_SYSTEM_PROMPT = (
    "You are an orchestrator. Given a user task and a catalog of agents, "
    "produce a JSON array of calls to fulfill the task. Each element is "
    '{"agent": <agent name>, "input": <text to send>}. Call agents in order; '
    f'use the literal string "{PREVIOUS_OUTPUT_PLACEHOLDER}" inside an input to '
    "insert the previous call's output. Respond with ONLY the JSON array."
)


class PlannedCall(TypedDict):
    agent: str
    input: str


def cards_to_catalog(cards: dict[str, AgentCard]) -> str:
    lines = []
    for name, card in cards.items():
        skills = ", ".join(skill.name for skill in card.skills)
        lines.append(f"- {name}: {card.description} (skills: {skills})")
    return "\n".join(lines)


def _parse_plan(raw: str) -> list[PlannedCall]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    payload = match.group(0) if match else raw
    parsed = json.loads(payload)
    plan: list[PlannedCall] = []
    for item in parsed:
        if isinstance(item, dict) and "agent" in item and "input" in item:
            plan.append({"agent": str(item["agent"]), "input": str(item["input"])})
    return plan


async def plan_calls(
    task: str,
    cards: dict[str, AgentCard],
    model=None,
    max_calls: int = 5,
) -> list[PlannedCall]:
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    catalog = cards_to_catalog(cards)
    response = await model.ainvoke(
        [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\nAgents:\n{catalog}"},
        ]
    )
    plan = _parse_plan(response.content)
    known = [call for call in plan if call["agent"] in cards]
    return known[:max_calls]
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_planner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/planner.py tests/test_planner.py
git commit -m "feat: LLM 동적 라우팅 planner 추가"
```

---

## Task 9: 오케스트레이터 — orchestrate & CLI

**Files:**
- Create: `orchestrator/orchestrate.py`, `orchestrator/__main__.py`
- Test: `tests/test_orchestrate.py`에 실행 흐름 테스트 추가

**Interfaces:**
- Consumes: `discover_agents` (Task 7), `call_agent` (Task 7), `plan_calls`/`PREVIOUS_OUTPUT_PLACEHOLDER` (Task 8)
- Produces:
  - `orchestrator/orchestrate.py`:
    - `async def execute_plan(http, cards, plan, call_agent_fn=call_agent) -> list[dict]` — 계획대로 순차 호출, `{PREVIOUS_OUTPUT}`를 직전 출력으로 치환, 각 단계 `{"agent","input","output"}` 기록. 호출 실패 시 output에 에러 문자열.
    - `async def synthesize(task, steps, model=None) -> str` — LLM이 수집 결과를 최종 답변으로 종합.
    - `async def run_task(task: str, model=None) -> str` — discover→plan→execute→synthesize 전체.
  - `orchestrator/__main__.py`: CLI. `python -m orchestrator "<task>"`.

- [ ] **Step 1: 실패하는 테스트 작성 (execute_plan — 가짜 call_agent 주입)**

```python
from orchestrator.orchestrate import execute_plan
from orchestrator.planner import PREVIOUS_OUTPUT_PLACEHOLDER


async def test_execute_plan_chains_previous_output():
    # given — 두 단계: research 출력이 summarizer 입력으로 치환되어야 함
    cards = {"research": object(), "summarizer": object()}
    plan = [
        {"agent": "research", "input": "quantum computing"},
        {"agent": "summarizer", "input": PREVIOUS_OUTPUT_PLACEHOLDER},
    ]
    calls = []

    async def fake_call_agent(http, card, text):
        calls.append(text)
        return f"output-for:{text}"

    # when
    steps = await execute_plan(
        http=None, cards=cards, plan=plan, call_agent_fn=fake_call_agent
    )

    # then
    assert calls[0] == "quantum computing"
    assert calls[1] == "output-for:quantum computing"  # placeholder 치환됨
    assert steps[1]["output"] == "output-for:output-for:quantum computing"


async def test_execute_plan_records_error_on_failure():
    # given
    cards = {"research": object()}
    plan = [{"agent": "research", "input": "x"}]

    async def failing_call_agent(http, card, text):
        raise RuntimeError("connection refused")

    # when
    steps = await execute_plan(
        http=None, cards=cards, plan=plan, call_agent_fn=failing_call_agent
    )

    # then
    assert "connection refused" in steps[0]["output"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_orchestrate.py::test_execute_plan_chains_previous_output -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.orchestrate'`

- [ ] **Step 3: `orchestrator/orchestrate.py` 구현**

```python
"""과업을 discover→plan→execute→synthesize로 수행하는 오케스트레이션 책임."""
import httpx

from orchestrator.registry import discover_agents
from orchestrator.client import call_agent
from orchestrator.planner import plan_calls, PREVIOUS_OUTPUT_PLACEHOLDER

SYNTHESIS_SYSTEM_PROMPT = (
    "You are an orchestrator. Given the original task and the outputs collected "
    "from sub-agents, write the final answer for the user."
)


async def execute_plan(http, cards, plan, call_agent_fn=call_agent) -> list[dict]:
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
    return response.content


async def run_task(task: str, model=None) -> str:
    async with httpx.AsyncClient() as http:
        cards = await discover_agents(http)
        if not cards:
            return "No agents available."
        plan = await plan_calls(task, cards, model=model)
        if not plan:
            return "Planner produced no executable calls."
        steps = await execute_plan(http, cards, plan)
        return await synthesize(task, steps, model=model)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_orchestrate.py -v`
Expected: PASS (전체)

- [ ] **Step 5: `orchestrator/__main__.py` 구현**

```python
"""오케스트레이터 CLI 진입점: python -m orchestrator "<task>"."""
import asyncio
import sys

from dotenv import load_dotenv

from orchestrator.orchestrate import run_task

load_dotenv()


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m orchestrator "<task>"')
        raise SystemExit(1)
    task = sys.argv[1]
    answer = asyncio.run(run_task(task))
    print(answer)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/orchestrate.py orchestrator/__main__.py tests/test_orchestrate.py
git commit -m "feat: 오케스트레이션 실행 흐름 및 CLI 추가"
```

---

## Task 10: 실행 스크립트, README, 수동 E2E 검증

**Files:**
- Create: `scripts/run_all.sh`, `README.md` (덮어쓰기 — 현재 빈 파일)

**Interfaces:**
- Consumes: 전체 시스템
- Produces: 실행 스크립트 + 문서 + 검증된 동작 PoC

- [ ] **Step 1: `scripts/run_all.sh` 작성**

```bash
#!/usr/bin/env bash
# 두 에이전트 서버를 백그라운드로 띄우고, 종료 시 정리한다.
set -euo pipefail

python -m agents.research &
RESEARCH_PID=$!
python -m agents.summarizer &
SUMMARIZER_PID=$!

cleanup() {
  kill "$RESEARCH_PID" "$SUMMARIZER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "research (pid $RESEARCH_PID) on :9001, summarizer (pid $SUMMARIZER_PID) on :9002"
echo "press Ctrl-C to stop"
wait
```

Run: `chmod +x scripts/run_all.sh`

- [ ] **Step 2: `README.md` 작성**

````markdown
# A2A Multi-Agent Orchestration PoC

독립 A2A 서버로 뜬 Research/Summarizer 에이전트를 LLM 동적 라우팅
오케스트레이터가 조합해 "리서치 → 요약" 과업을 수행한다.

## 설정

```bash
pip install -e ".[dev]"
cp .env.example .env   # OPENAI_API_KEY, TAVILY_API_KEY 채우기
```

## 실행

```bash
# 1) 에이전트 서버 2개 기동
./scripts/run_all.sh
#   또는 각각:
#   python -m agents.research      # :9001
#   python -m agents.summarizer    # :9002

# 2) 다른 터미널에서 과업 실행
python -m orchestrator "양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"
```

각 에이전트의 Agent Card는
`http://127.0.0.1:9001/.well-known/agent-card.json` 에서 확인할 수 있다.

## 테스트

```bash
pytest -v
```

테스트는 OpenAI/Tavily 호출을 가짜로 대체해 네트워크 없이 돈다.

## 구조

- `common/` — AgentCard 빌더, LangGraph→A2A executor 어댑터, 서버 조립
- `agents/<name>/` — 에이전트별 graph + card + server 진입점
- `orchestrator/` — discovery, A2A 클라이언트, LLM planner, 실행 흐름

새 에이전트 추가: `agents/<name>/`에 `graph.py`/`card.py`/`__main__.py`를
작성하고 `orchestrator/registry.py`의 `AGENT_URLS`에 URL 한 줄 추가.
````

- [ ] **Step 3: 전체 자동 테스트 통과 확인**

Run: `pytest -v`
Expected: 모든 테스트 PASS (agent_card, langgraph_executor 3, server, research_graph, summarizer_graph, planner 4, orchestrate)

- [ ] **Step 4: 수동 E2E 검증 (실제 키 필요)**

`.env`에 실제 `OPENAI_API_KEY`, `TAVILY_API_KEY`가 있을 때:

1. Run: `./scripts/run_all.sh` (백그라운드 서버 기동)
2. 별도 터미널 Run: `curl -s http://127.0.0.1:9001/.well-known/agent-card.json | head`
   Expected: `research` 카드 JSON 노출
3. Run: `python -m orchestrator "양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"`
   Expected: research가 Tavily로 자료 수집 → summarizer가 요약 → 최종 종합 답변 출력
4. 키가 없으면 이 단계는 "수동 검증 보류"로 기록하고 자동 테스트(Step 3) 통과로 갈음.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_all.sh README.md
git commit -m "docs: 실행 스크립트 및 README 추가"
```

---

## Self-Review 결과

**Spec coverage:** spec의 모든 요소가 태스크로 매핑됨 —
독립 A2A 서버(Task 4,5,6), Agent Card discovery(Task 7), LLM 동적 라우팅
plan→execute→synthesize(Task 8,9), 공통 추상화(Task 2,3,4),
리서치+요약 시나리오(Task 5,6,9), 에러 처리(Task 3 executor 실패, Task 7
discovery skip, Task 8 unknown agent 필터, Task 9 호출 실패 기록, max_calls
가드), 테스트 전략(각 태스크 가짜 LLM/tool 주입), 실행 방법(Task 10).

**버전 검증:** a2a-sdk 1.1.0의 핵심 API(AgentCard protobuf + supported_interfaces,
executor의 new_task_from_user_message + enqueue, DefaultRequestHandler 3-arg,
create_*_routes, ClientFactory/A2ACardResolver, StreamResponse.payload oneof)를
실제 서버+클라이언트 왕복 스파이크로 검증 완료. 계획의 서버/클라이언트 코드는
검증된 패턴을 그대로 사용.

**주의 사항(구현 중 확인):** `RequestContext`/`EventQueue`의 테스트용 생성자
시그니처, route 객체의 `.path` 속성명은 SDK 내부 구현이라 테스트 헬퍼에서
필요 시 조정한다(해당 태스크 Step 4에 명시). 구현 로직 자체는 검증됨.
