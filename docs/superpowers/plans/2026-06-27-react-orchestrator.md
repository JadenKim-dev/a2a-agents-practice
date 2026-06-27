# ReAct 오케스트레이터 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 오케스트레이터의 수동 `plan→execute→synthesize` 파이프라인을 LangGraph ReAct 에이전트로 교체한다.

**Architecture:** 원격 A2A 에이전트 호출을 단일-인자 LLM tool로 감싸고(`orchestrator/agent_tool.py`), 요청당 빌드 함수가 discover된 카드로 tool을 동적 생성해 `create_agent`(LangGraph prebuilt ReAct)에 넘긴다. 호출 순서·데이터 전달·종합은 ReAct 루프 안에서 LLM이 결정하며 `recursion_limit`으로 가드한다.

**Tech Stack:** Python 3.11+, langchain `create_agent` (langchain 1.3.x), langgraph 1.2.x, langchain-core `StructuredTool`, a2a-sdk 1.1.0, pytest + pytest-asyncio (`asyncio_mode=auto`).

## Global Constraints

- 의존성: `langgraph>=1.2,<2`, `langchain-openai>=1.3,<2` (pyproject.toml 고정값, 신규 의존성 추가 금지)
- `run_task` 시그니처는 CLI(`orchestrator/__main__.py`)와의 호환을 위해 `async def run_task(task, model=None, ...) -> str`를 유지한다
- 기본 LLM 모델은 `gpt-4o-mini` (lazy import: `from langchain_openai import ChatOpenAI`)
- docstring은 한글로, 책임을 서술형("~한다")으로 작성한다
- 선언 순서(CLAUDE.md): static→instance, 필드→메서드, public→private, caller→callee. 같은 우선순위 충돌 시 필드-우선이 visibility를 이긴다
- 테스트(CLAUDE.md): 각 케이스에 `# given`/`# when`/`# then` 주석, 입력은 `it`(=`def test_`) 블록 내 리터럴, per-field `assert`, 동작 기반 케이스명
- 테스트는 LLM·네트워크를 가짜로 대체해 결정론적으로 만든다 (실제 OpenAI/Tavily 호출 없음)

---

## File Structure

| 파일 | 상태 | 책임 |
|------|------|------|
| `orchestrator/agent_tool.py` | 신규 | 원격 A2A 카드 1개 → ReAct가 호출 가능한 단일-인자 LLM tool 변환 + tool 레벨 에러 캐치 |
| `orchestrator/orchestrate.py` | 재작성 | discover→build_orchestrator_graph→ReAct invoke 실행 흐름 |
| `orchestrator/planner.py` | 삭제 | (ReAct가 라우팅을 흡수) |
| `tests/test_agent_tool.py` | 신규 | `tool_description`, `build_agent_tool`(정상/에러) 검증 |
| `tests/test_orchestrate.py` | 재작성 | `run_task` ReAct 흐름·에이전트 0개 검증 + 기존 `extract_response_text` 테스트 유지 |
| `tests/test_planner.py` | 삭제 | (planner.py 삭제에 동반) |
| `orchestrator/registry.py` | 무변경 | discover |
| `orchestrator/client.py` | 무변경 | `call_agent`, `extract_response_text` |
| `orchestrator/llm.py` | 무변경 | `message_content_to_text` (마지막 메시지 추출에 재사용) |
| `orchestrator/__main__.py` | 무변경 | CLI 진입점 |

각 Task는 독립적으로 테스트 가능한 산출물로 끝난다. Task 1(agent_tool)이 Task 2(orchestrate)의 의존이므로 순서대로 진행한다.

---

## Task 1: agent_tool.py — 카드를 LLM tool로 변환

**Files:**
- Create: `orchestrator/agent_tool.py`
- Test: `tests/test_agent_tool.py`

**Interfaces:**
- Consumes: `orchestrator.client.call_agent(http, card, text) -> str` (기존), `common.agent_card.build_agent_card(name, description, url, skill_id, skill_name, skill_description, skill_tags)` (테스트 fixture용, 기존)
- Produces:
  - `tool_description(card) -> str`
  - `build_agent_tool(http, name, card, call_agent_fn=call_agent) -> StructuredTool` — 생성된 tool은 `.name == name`, `.description == tool_description(card)`, `.coroutine(input=str)` 호출 시 `call_agent_fn(http, card, input)`로 위임하고 예외는 `"[error calling {name}: {error}]"` 문자열로 흡수

- [ ] **Step 1: Write the failing tests**

`tests/test_agent_tool.py` 생성:

```python
from common.agent_card import build_agent_card
from orchestrator.agent_tool import build_agent_tool, tool_description


def _research_card():
    return build_agent_card(
        name="research",
        description="Researches a topic using web search.",
        url="http://127.0.0.1:9001/",
        skill_id="research",
        skill_name="Web Research",
        skill_description="Find current information on a topic.",
        skill_tags=["research"],
    )


def test_tool_description_includes_card_description_and_skill_name():
    # given
    card = _research_card()

    # when
    description = tool_description(card)

    # then
    assert "Researches a topic using web search." in description
    assert "Web Research" in description


def test_build_agent_tool_names_tool_after_agent():
    # given
    card = _research_card()

    # when
    tool = build_agent_tool(http=None, name="research", card=card)

    # then
    assert tool.name == "research"
    assert tool.description == tool_description(card)


async def test_build_agent_tool_delegates_input_to_call_agent():
    # given
    card = _research_card()
    received = {}

    async def fake_call_agent(http, card_arg, text):
        received["card"] = card_arg
        received["text"] = text
        return f"briefing-for:{text}"

    tool = build_agent_tool(
        http="HTTP", name="research", card=card, call_agent_fn=fake_call_agent
    )

    # when
    output = await tool.coroutine(input="quantum computing")

    # then
    assert received["text"] == "quantum computing"
    assert received["card"] is card
    assert output == "briefing-for:quantum computing"


async def test_build_agent_tool_absorbs_call_failure_into_text():
    # given
    card = _research_card()

    async def failing_call_agent(http, card_arg, text):
        raise RuntimeError("connection refused")

    tool = build_agent_tool(
        http=None, name="research", card=card, call_agent_fn=failing_call_agent
    )

    # when
    output = await tool.coroutine(input="x")

    # then
    assert "connection refused" in output
    assert "research" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_agent_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.agent_tool'`

- [ ] **Step 3: Write the implementation**

`orchestrator/agent_tool.py` 생성:

```python
"""원격 A2A 에이전트 카드를 ReAct가 호출 가능한 LLM tool로 변환한다."""
from langchain_core.tools import StructuredTool

from a2a.types import AgentCard

from orchestrator.client import call_agent


def build_agent_tool(http, name: str, card: AgentCard, call_agent_fn=call_agent) -> StructuredTool:
    """원격 A2A 에이전트 하나를 ReAct가 호출 가능한 단일-인자 tool로 감싼다."""
    async def call(input: str) -> str:
        try:
            return await call_agent_fn(http, card, input)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_agent_tool.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agent_tool.py tests/test_agent_tool.py
git commit -m "feat: 카드를 ReAct LLM tool로 변환하는 agent_tool 추가"
```

---

## Task 2: orchestrate.py 재작성 — ReAct 실행 흐름

**Files:**
- Modify (전면 재작성): `orchestrator/orchestrate.py`
- Modify (재작성): `tests/test_orchestrate.py`

**Interfaces:**
- Consumes:
  - `orchestrator.agent_tool.build_agent_tool(http, name, card, call_agent_fn=call_agent)` (Task 1)
  - `orchestrator.registry.discover_agents(http) -> dict[str, AgentCard]` (기존)
  - `orchestrator.llm.message_content_to_text(message) -> str` (기존)
  - `langchain.agents.create_agent(model, tools, system_prompt) -> CompiledStateGraph`
  - `langgraph.errors.GraphRecursionError`
- Produces:
  - `build_orchestrator_graph(http, cards, model=None) -> CompiledStateGraph`
  - `async run_task(task, model=None, recursion_limit=10) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_orchestrate.py` 전체를 다음으로 교체 (기존 `extract_response_text` 테스트는 유지, `execute_plan` 테스트는 제거):

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, Message, Part, Role, StreamResponse
from a2a.types import Task, TaskStatus, TaskState

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
```

> 참고: `fake_call_agent`를 `orchestrator.agent_tool.call_agent`에 monkeypatch하는 이유 — `build_agent_tool`의 `call_agent_fn` 기본값이 import 시점에 바인딩되므로, 모듈 속성을 패치하면 기본값 경로가 가짜로 대체된다. (`build_orchestrator_graph`는 `call_agent_fn`을 명시 주입하지 않고 기본값을 쓴다.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_orchestrate.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_task'` 또는 `AttributeError` (재작성 전 orchestrate.py에는 아직 새 구조 없음). 실제로는 기존 `run_task`가 있으므로 `test_run_task_*`가 FAIL (monkeypatch 대상 `discover_agents`는 있으나 새 동작 없음).

- [ ] **Step 3: Write the implementation**

`orchestrator/orchestrate.py` 전체를 다음으로 교체:

```python
"""Task를 ReAct 에이전트로 오케스트레이션해 동적 라우팅·종합을 수행한다."""
import httpx
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from orchestrator.registry import discover_agents
from orchestrator.agent_tool import build_agent_tool
from orchestrator.llm import message_content_to_text

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are an orchestrator with access to specialist agent tools. "
    "Use the tools to fulfill the user's task, feeding one tool's output "
    "into the next as needed, then write the final answer for the user."
)


async def run_task(task: str, model=None, recursion_limit: int = 10) -> str:
    """Task에 대해 discover→build→ReAct 실행 전체 파이프라인을 수행한다."""
    async with httpx.AsyncClient() as http:
        cards = await discover_agents(http)
        if not cards:
            return "No agents available."
        graph = build_orchestrator_graph(http, cards, model)
        try:
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": task}]},
                {"recursion_limit": recursion_limit},
            )
        except GraphRecursionError:
            return "Orchestration exceeded the step limit."
        return message_content_to_text(result["messages"][-1])


def build_orchestrator_graph(http, cards, model=None):
    """discover된 카드마다 원격 호출 tool을 만들어 ReAct 에이전트 그래프를 생성한다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    tools = [build_agent_tool(http, name, card) for name, card in cards.items()]
    return create_agent(
        model=model, tools=tools, system_prompt=ORCHESTRATOR_SYSTEM_PROMPT
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_orchestrate.py -v`
Expected: PASS (5 passed: extract_response_text + 4 run_task 케이스)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrate.py tests/test_orchestrate.py
git commit -m "refactor: 오케스트레이터를 ReAct 에이전트 실행 흐름으로 재작성"
```

---

## Task 3: planner.py 및 planner 테스트 제거

**Files:**
- Delete: `orchestrator/planner.py`
- Delete: `tests/test_planner.py`

**Interfaces:**
- Consumes: 없음 (제거만 수행)
- Produces: 없음. Task 2 이후 `planner`를 import하는 코드가 없어야 한다.

- [ ] **Step 1: 잔여 import 없음을 확인**

Run: `grep -rn "planner" orchestrator/ agents/ common/ tests/ --include="*.py"`
Expected: 출력 없음 (Task 2에서 orchestrate.py가 planner를 더는 import하지 않음). 만약 `tests/test_planner.py`만 잡히면 정상 — 다음 스텝에서 삭제된다.

- [ ] **Step 2: 파일 삭제**

```bash
git rm orchestrator/planner.py tests/test_planner.py
```

- [ ] **Step 3: 전체 테스트 통과 확인**

Run: `.venv/bin/pytest -v`
Expected: PASS — 모든 테스트 통과, planner 관련 테스트는 수집되지 않음. 기존 에이전트/executor/llm/server/card 테스트는 영향 없이 통과.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: ReAct 전환으로 불필요해진 planner 제거"
```

---

## Task 4: 설계 문서 동기화

**Files:**
- Modify: `docs/superpowers/specs/2026-06-24-a2a-multi-agent-orchestration-design.md`

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (문서 정합성만 확보)

기존 design 문서의 "오케스트레이터 측 (LLM 동적 라우팅)" 서술이 단발 plan 방식을 설명하는데, 구현이 ReAct로 바뀌었으므로 그 절에 ReAct 전환을 가리키는 한 줄을 추가한다. (CLAUDE.md 문서 보존 규칙: spec은 유지하되 실제 구현과 어긋나지 않게 동기화.)

- [ ] **Step 1: design 문서의 "B. 오케스트레이터 측" 절 상단에 전환 안내 추가**

`docs/superpowers/specs/2026-06-24-a2a-multi-agent-orchestration-design.md`의 `### B. 오케스트레이터 측 (LLM 동적 라우팅)` 헤더 바로 아래에 다음 문장을 삽입:

```markdown
> **갱신(2026-06-27):** 아래의 단발 plan 방식은 ReAct 에이전트 방식으로
> 대체되었다. 상세는 [react-orchestrator-design](2026-06-27-react-orchestrator-design.md)
> 참조. 호출 순서·입력·종합을 LLM이 ReAct 루프 안에서 매 스텝 결정한다.
```

- [ ] **Step 2: 변경 확인**

Run: `grep -n "ReAct 에이전트 방식으로" docs/superpowers/specs/2026-06-24-a2a-multi-agent-orchestration-design.md`
Expected: 삽입한 줄이 출력됨

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-24-a2a-multi-agent-orchestration-design.md
git commit -m "docs: 기존 설계 문서에 ReAct 전환 안내 동기화"
```

---

## Self-Review

**1. Spec coverage:**
- agent_tool.py(build_agent_tool/tool_description, tool 레벨 에러) → Task 1 ✓
- orchestrate.py 재작성(run_task/build_orchestrator_graph, recursion_limit, GraphRecursionError, "No agents available.") → Task 2 ✓
- planner.py 제거 → Task 3 ✓
- 테스트 대체(test_agent_tool 신규, test_orchestrate 재작성, test_planner 제거, extract_response_text 유지) → Task 1·2·3 ✓
- 기존 design 문서 동기화 → Task 4 ✓ (spec "기존 design 문서와의 관계" 절 반영)
- 유지 파일(registry/client/llm/__main__) 무변경 → 모든 Task에서 건드리지 않음 ✓

**2. Placeholder scan:** "TBD"/"TODO"/"적절히"/"비슷하게" 없음. 모든 코드 스텝에 완전한 코드 포함. ✓

**3. Type consistency:**
- `build_agent_tool(http, name, card, call_agent_fn=call_agent)` — Task 1 정의, Task 2에서 `build_agent_tool(http, name, card)`로 기본값 사용 (일관) ✓
- `tool_description(card)` — Task 1 정의·테스트, Task 2 미사용 (간접) ✓
- `run_task(task, model=None, recursion_limit=10)` — Task 2 정의, 테스트에서 `model=`/`recursion_limit=` 주입 (일관) ✓
- `ToolCallingFakeModel.bind_tools(self, tools, **kwargs) -> self` — 실 검증 완료(GenericFakeChatModel 기반) ✓
- monkeypatch 대상: `orchestrator.orchestrate.discover_agents`, `orchestrator.agent_tool.call_agent` — 각 모듈의 실제 import 위치와 일치 ✓
```
