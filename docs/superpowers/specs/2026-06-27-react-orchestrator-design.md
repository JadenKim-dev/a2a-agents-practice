# 오케스트레이터를 LangGraph ReAct Agent로 전환 — 설계

작성일: 2026-06-27

## 목표

오케스트레이터의 수동 `plan→execute→synthesize` 파이프라인을 LangGraph ReAct
에이전트(`langchain.agents.create_agent`)로 교체한다. 원격 A2A 에이전트 호출을
LLM tool로 감싸, 호출 순서·각 에이전트로 보낼 입력·중간 결과 반영·최종 종합을
모두 ReAct 루프 안에서 LLM이 결정하게 한다.

에이전트 내부 두뇌는 이미 `create_agent`(LangGraph prebuilt ReAct)로 동작하는데,
오케스트레이터만 수동 파이프라인으로 남아 있다. 이 전환으로 오케스트레이터를
에이전트들과 같은 추상화로 통일한다.

## 동기 (왜 바꾸는가)

기존 [orchestrate.py](../../../orchestrator/orchestrate.py) /
[planner.py](../../../orchestrator/planner.py)의 한계:

- **계획이 선형·단발성이다.** LLM이 처음에 `[{agent, input}, ...]` JSON 배열을
  한 번 뽑으면 끝이고, 중간 결과를 보고 "다시 검색 / 이 에이전트는 건너뛰기"
  같은 적응이 불가능하다.
- **데이터 전달이 placeholder 문자열 치환뿐이다** (`{PREVIOUS_OUTPUT}`).
  분기·병합이 안 된다.
- **JSON 생성 → 정규식 추출 → `json.loads` → 필터링**이라는 취약한 파싱 사슬을
  코드가 직접 떠안고 있다.

ReAct는 표준 tool-calling으로 이 사슬을 없애고, 매 스텝 LLM이 적응적으로
다음 행동을 결정한다. 이 PoC의 명시 목표("Agent Card 근거 동적 라우팅,
에이전트 추가 시 오케스트레이터 코드 무수정")에 오히려 더 충실하다.

## 설계 결정 (확정)

| 항목 | 결정 | 근거 |
|------|------|------|
| 루프 가드 | LangGraph `recursion_limit` | 표준 방식, 추가 코드 없음. `max_calls=5` 하드 제한 대체 |
| 결과 종합 | ReAct 루프에 흡수 | 루프 종료 시 LLM이 도구 출력을 종합해 최종 답변 생성. 별도 `synthesize` LLM 호출 제거 |
| 그래프 생성 | 요청당 빌드 함수 | `build_orchestrator_graph(http, cards, model)`이 discover된 카드로 tool을 동적 생성. http·card는 클로저로 캡처 |
| 전환 범위 | CLI 유지, 내부만 교체 | `run_task` 시그니처와 CLI 진입점 유지. 오케스트레이터의 A2A 서버 노출은 범위 밖 |
| tool 변환 위치 | 별도 파일 `orchestrator/agent_tool.py` | "카드 → LLM tool 변환"은 "discover→build→run 흐름"과 다른 단일 책임 |

## 아키텍처

```
[전환 전 — 수동 4단계]
run_task → discover → plan_calls(JSON 생성·정규식 파싱)
         → execute_plan(순차·placeholder 치환) → synthesize(별도 LLM)

[전환 후 — ReAct 단일 루프]
run_task → discover → build_orchestrator_graph(http, cards, model)
         → graph.ainvoke(task, {recursion_limit}) → 마지막 메시지 추출
                              │
                              └─ 카드마다 동적 tool 생성 (http·card 클로저 캡처)
                                 create_agent(model, tools, system_prompt)

[ReAct 루프 내부] LLM이 "도구 호출 ↔ 결과 관찰"을 반복하며 스스로
라우팅·데이터 전달·종합. recursion_limit으로 가드.
```

## 컴포넌트 & 파일별 책임

### 신규: `orchestrator/agent_tool.py`

원격 A2A 에이전트 카드 하나를 ReAct가 호출 가능한 단일-인자 LLM tool로 변환한다.

```python
def build_agent_tool(http, name, card, call_agent_fn=call_agent):
    """원격 A2A 에이전트 하나를 ReAct가 호출 가능한 단일-인자 tool로 감싼다."""
    async def call(input: str) -> str:
        try:
            return await call_agent_fn(http, card, input)
        except Exception as error:  # noqa: BLE001 — 루프 무중단 보장
            return f"[error calling {name}: {error}]"
    return StructuredTool.from_function(
        coroutine=call,
        name=name,
        description=tool_description(card),
    )

def tool_description(card) -> str:
    """카드의 description과 skill 이름을 LLM tool description 문자열로 합친다."""
    skills = ", ".join(skill.name for skill in card.skills)
    return f"{card.description} (skills: {skills})"
```

- LLM에 노출되는 인자는 `input: str` 하나뿐. `http`·`card`는 클로저로 캡처한다.
- tool 이름 = 카드 이름, description = `card.description` + skills.
  `tool_description`은 기존 planner의 `cards_to_catalog` 카드→텍스트 변환을
  카드 단위로 재사용한 것이다.
- **에러 처리:** tool 내부에서 예외를 잡아 `"[error calling {name}: {error}]"`
  문자열을 반환한다. 예외를 그래프로 전파하지 않아야 LLM이 "이 에이전트는
  실패했다"를 ToolMessage로 관찰하고 다른 경로를 시도하거나 종합에 반영한다.
  (기존 `execute_plan`의 try/except를 tool 레벨로 옮긴 것.)

### 재작성: `orchestrator/orchestrate.py`

discover→build→ReAct 실행 흐름을 담당한다.

```python
ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are an orchestrator with access to specialist agent tools. "
    "Use the tools to fulfill the user's task, feeding one tool's output "
    "into the next as needed, then write the final answer for the user."
)

async def run_task(task, model=None, recursion_limit=10) -> str:
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

**선언 순서** (CLAUDE.md): 상수 → `run_task`(public, caller) →
`build_orchestrator_graph`(public, callee). 둘 다 public이므로 caller→callee
순으로 `run_task`를 위에 둔다.

### 유지 (변경 없음)

- `registry.py` — discover
- `client.py` — `call_agent`, `extract_response_text`
- `llm.py` — `message_content_to_text` (마지막 메시지 추출에 재사용)
- `__main__.py` — CLI 진입점 (`run_task` 시그니처 유지로 무변경)

### 제거

- `orchestrator/planner.py` — 전체 삭제 (`plan_calls`, `cards_to_catalog`,
  `_parse_plan`, `PlannedCall`, `PREVIOUS_OUTPUT_PLACEHOLDER`)
- `orchestrate.py`의 `execute_plan`, `synthesize`, `StepResult`,
  `SYNTHESIS_SYSTEM_PROMPT`

## 데이터 흐름

placeholder 치환이 사라지고 LLM이 도구 인자를 직접 구성한다.

```
task → graph.ainvoke({"messages":[user]}, {recursion_limit})
  → [ReAct] LLM이 research(input="...") 호출
       → tool이 call_agent로 원격 위임 → 결과를 ToolMessage로 관찰
  → [ReAct] LLM이 그 결과를 보고 summarizer(input="<research 결과>") 호출 → 관찰
  → [ReAct] 더 부를 도구 없음 → 최종 답변 AIMessage 생성
  → result["messages"][-1] 추출
```

## 에러 처리

| 상황 | 처리 |
|------|------|
| discover 0개 | `"No agents available."` 반환 (현행 유지) |
| 원격 에이전트 호출 실패 | tool 내부에서 예외를 잡아 `"[error calling {name}: {error}]"` 반환 → LLM이 ToolMessage로 관찰 |
| recursion_limit 초과 | `run_task`가 `GraphRecursionError`를 잡아 `"Orchestration exceeded the step limit."` 반환 |
| LLM이 없는 에이전트 호출 | tool은 discover된 카드로만 생성되므로 애초에 존재하지 않는 도구는 노출되지 않음 (별도 필터링 불필요) |

## 테스트 전략

기존 `test_orchestrate.py`의 `execute_plan` 테스트(placeholder 치환·에러 기록)와
`test_planner.py`는 대상 코드가 사라지므로 제거하고 다음으로 대체한다.

| 대상 | 방식 |
|------|------|
| `agent_tool.tool_description` | fake card 주입 → description 문자열에 card.description과 skill 이름이 포함됨 검증 |
| `agent_tool.build_agent_tool` (정상) | fake card + fake call_agent 주입 → 생성된 tool의 `name`이 카드 이름과 일치, 호출 시 `call_agent`로 위임됨 검증 (네트워크 없음) |
| `agent_tool.build_agent_tool` (에러) | fake call_agent가 raise → tool이 `"[error calling ...]"` 문자열을 반환(예외 전파 안 함) 검증 |
| `orchestrate.run_task` 흐름 | fake model이 tool_call을 담은 `AIMessage` → 최종 `AIMessage`를 순서대로 반환 → research·summarizer tool이 불리고 최종 텍스트가 반환됨 검증 |
| `orchestrate.run_task` (에이전트 0개) | discover가 빈 dict → `"No agents available."` 반환 검증 |
| `client.extract_response_text` | 현행 테스트 유지 (변경 없음) |

**fake model로 tool-calling 흉내내기:** `FakeMessagesListChatModel`의
`responses`에 `tool_calls`를 가진 `AIMessage`(도구 호출 단계)와 그 뒤
plain `AIMessage`(최종 답변 단계)를 순서대로 넣어 ReAct 루프를 결정론적으로
구동한다. `build_agent_tool`에 fake call_agent를 주입할 수 있도록
`call_agent`를 선택적 인자로 받게 한다 (`execute_plan`의 `call_agent_fn`
주입 패턴과 동일한 결).

CLAUDE.md 테스트 규칙 준수: given/when/then 주석, 입력은 `it` 블록 내 리터럴,
per-field expect, 동작 기반 케이스명.

## 범위 밖 (확장 지점)

기존 design 문서의 확장 지점을 그대로 승계한다.

- 스트리밍 응답 (`message/stream`)
- 오케스트레이터 자신을 A2A 서버로 노출 (재귀적 위임)
- 멀티턴 컨텍스트(contextId) 유지
- tool 호출 수 정밀 카운트 (현재는 `recursion_limit`으로 충분)

## 기존 design 문서와의 관계

[2026-06-24-a2a-multi-agent-orchestration-design.md](2026-06-24-a2a-multi-agent-orchestration-design.md)의
"오케스트레이터 측 (LLM 동적 라우팅)" 절에서 서술한 단발 plan 방식
(planner.py가 호출 계획을 한 번에 산출)은 이 문서의 ReAct 방식으로 대체된다.
나머지(에이전트 서버 측 A2A 흐름, discovery, 디렉토리 구조)는 유효하다.
```
