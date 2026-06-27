# 오케스트레이터를 SSE 스트리밍 서버로 전환 — 설계

작성일: 2026-06-27

## 목표

오케스트레이터를 세 방향으로 개선한다.

1. **진행 상황 전달.** 현재 `run_task`는 `graph.ainvoke`로 한 번에 실행되어
   중간 진행 상황을 알 수 없다. `graph.astream`으로 바꿔 ReAct 루프의 매 스텝을
   진행 이벤트로 흘린다.
2. **서버 + SSE.** CLI 스크립트 실행 방식을 제거하고 HTTP 서버로 노출한다.
   `POST /run`이 진행 이벤트를 SSE(Server-Sent Events)로 스트리밍한다.
3. **step limit graceful degradation.** 현재는 `recursion_limit` 초과 시
   `GraphRecursionError`를 잡아 `"Orchestration exceeded the step limit."`만
   반환하고 끝난다. 그때까지 수집한 정보로 부족하게라도 종합 답변을 만든다.
   이 종합을 **LangGraph 그래프 내부**에 미들웨어로 통합해 그래프 밖
   try/except fallback을 피한다.

## 설계 결정 (확정)

| 항목 | 결정 | 근거 |
|------|------|------|
| 서버 형식 | 일반 HTTP + SSE (A2A 아님) | 오케스트레이터는 에이전트 호출의 '입구'이지 '에이전트'가 아니다. A2A의 status/artifact 이벤트 스키마에 ReAct 중간 진행을 억지로 맞추는 것보다, 진행 이벤트 스키마를 자유롭게 설계하는 편이 명확하다 |
| 웹 프레임워크 | starlette (`StreamingResponse`) | `a2a-sdk[http-server]`가 이미 starlette를 끌어온다. FastAPI를 새로 추가하지 않아 의존성이 늘지 않고, 에이전트 서버(`common/server.py`)와 동일한 스택을 유지한다 |
| 이벤트 세분도 | 스텝 단위 | `astream(stream_mode="updates")`로 노드 출력 단위(tool 호출 / tool 결과 / 최종 답변)를 받는다. 토큰 단위 스트리밍보다 구현이 명확하고, 사용자가 "지금 research 호출 중 → summarizer 호출 중"을 이해하기에 충분하다 |
| step limit 종합 | `wrap_model_call` 미들웨어 | 한도 직전 스텝에서 tools를 비우고 "지금 종합하라" 지시로 모델을 호출한다. 그래프 내부에서 진짜 종합 답변을 만들고 `GraphRecursionError`가 발생하지 않아 SSE 스트림이 깔끔하게 닫힌다 |
| 진입점 | CLI 제거, 서버만 | `python -m orchestrator`는 이제 서버를 기동한다. CLI 인자(`"<task>"`) 방식은 제거한다 |
| 이벤트 변환 분리 | 별도 파일 `orchestrator/events.py` | "LangGraph chunk → 도메인 이벤트" 변환은 "discover→build→stream 흐름"과 다른 단일 책임이다. `agent_tool.py`를 분리한 것과 같은 결 |

### langchain 1.x API 확인 결과 (미들웨어 채택 근거)

이 프로젝트는 **langchain 1.x의 새 `create_agent`**(미들웨어 기반)를 사용한다
(`langchain.agents.create_agent`, 설치 버전 langchain 1.3.x / langgraph 1.2.x).
옛 `create_react_agent`의 `remaining_steps`·`pre_model_hook`·`post_model_hook`은
**새 `create_agent`에 존재하지 않는다**. 대신 미들웨어(`AgentMiddleware`)와
`jump_to`/`request.override`가 동일 역할을 한다.

- `wrap_model_call(request, handler)` / `awrap_model_call(...)`에서 모델 호출을
  가로채 `request.override(tools=[], system_message=...)`로 tools를 제거하고
  종합 지시를 주입할 수 있다. tools가 없으면 모델은 일반 `AIMessage`로 답하고
  그래프는 END로 라우팅된다 → 그래프 내부 종합, 에러 없음.
- 새 `create_agent`는 내부적으로 `recursion_limit: 9999`를 기본값으로 박아두지만,
  `ainvoke`/`astream` config에 넘긴 `recursion_limit`이 호출 단위로 이를
  override한다. 우리는 미들웨어의 호출 횟수 한도를 **실질 한도**로 삼고,
  `recursion_limit`은 미들웨어가 작동 안 할 경우의 **안전망**으로만 넉넉히 둔다.

## 아키텍처

```
[전환 전 — CLI 단발]
__main__.py (CLI "<task>") → run_task → graph.ainvoke (단발)
   → 최종 텍스트만 반환
   └ GraphRecursionError → "Orchestration exceeded the step limit." (수집물 폐기)

[전환 후 — SSE 스트리밍 서버]
__main__.py → uvicorn → orchestrator/server.py (starlette)
  POST /run  {task}  → text/event-stream
     └ run_task_stream(task)                         # orchestrate.py
          → discover → build_orchestrator_graph(미들웨어 포함)
          → async for chunk in graph.astream(stream_mode="updates"):
                event = to_progress_event(chunk)     # events.py
                if event: yield event
     └ server.py가 각 ProgressEvent를 SSE 라인으로 직렬화
          data: {"type":"tool_call","agent":"research","input":"..."}\n\n

[step limit 도달 시]
StepLimitSynthesisMiddleware.wrap_model_call
  → 한도 직전이면 request.override(tools=[], system_message="지금 종합하라")
  → 모델이 종합 AIMessage 생성 → final(truncated=true) 이벤트로 정상 방출
  → GraphRecursionError 없음 → SSE 정상 종료
```

## 컴포넌트 & 파일별 책임

### 신규: `orchestrator/middleware.py`

`StepLimitSynthesisMiddleware` — step limit 도달 직전에 강제 종합을 수행한다.

- `AgentMiddleware`를 상속하고 `awrap_model_call`(+동기 `wrap_model_call`)을
  구현한다.
- 상태의 모델 호출 횟수를 세어, `한도 - 1` 번째 호출이면
  `request.override(tools=[], system_message=<종합 지시>)`로 요청을 바꿔
  handler에 넘긴다. tools가 없으므로 모델은 일반 `AIMessage`로 답한다.
- 강제 종합으로 생성된 `AIMessage`에는 truncated 마킹을 남긴다(예:
  `response_metadata["truncated"] = True`). `events.py`가 이 마킹을 읽어
  `final.truncated`를 세팅한다.
- 생성자에서 `model_call_limit: int`를 받아 개별 필드로 저장한다.
- 종합 지시 시스템 메시지는 "더 이상 도구를 호출하지 말고, 지금까지 수집한
  정보만으로 사용자 task에 대한 최선의 답변을 작성하라"는 취지로 둔다.

### 신규: `orchestrator/events.py`

LangGraph stream chunk를 사용자에게 노출할 `ProgressEvent`로 변환한다 (변환만
책임지고 SSE 직렬화는 하지 않는다).

`ProgressEvent`의 `type`:

| type | 언제 | 필드 |
|------|------|------|
| `tool_call` | LLM이 에이전트 tool 호출을 결정 (`tool_calls`를 가진 `AIMessage`) | `agent`, `input` |
| `tool_result` | tool 결과 관찰 (`ToolMessage`) | `agent`, `output` |
| `final` | ReAct 종료/강제 종합 (tool_calls 없는 `AIMessage`) | `content`, `truncated` |
| `error` | 스트림 도중 예외 | `message` |

- `to_progress_event(chunk) -> ProgressEvent | None`이 핵심 함수.
  `astream(stream_mode="updates")`의 `{node_name: {"messages": [...]}}` chunk를
  해석해 위 타입으로 매핑한다. 매핑 대상이 아니면 `None`을 반환한다.
- `final.truncated`는 강제 종합 경로에서 `true`, 정상 종료에서 `false`.
  변환기 chunk 단독으로는 truncated 여부를 알 수 없다. 미들웨어가 강제 종합한
  `AIMessage`에 `response_metadata`로 마킹(예: `{"truncated": True}`)을 남기고,
  `to_progress_event`가 final 생성 시 그 마킹을 읽어 `truncated`에 반영한다.
  마킹이 없으면 기본 `false`. (orchestrate.py가 경로를 추측하지 않고, 종합을
  실제 수행한 미들웨어가 사실을 표시하는 쪽이 견고하다.)

### 신규: `orchestrator/server.py`

starlette 앱을 구성한다.

- `POST /run`: 요청 body의 `task`를 읽어 `run_task_stream(task)`를 구독하고,
  각 `ProgressEvent`를 `data: <json>\n\n` SSE 라인으로 직렬화해
  `StreamingResponse(media_type="text/event-stream")`로 반환한다.
- `build_app(run_stream=run_task_stream) -> Starlette` 형태로 의존성을 주입
  가능하게 해 테스트에서 fake stream을 넣는다.

### 재작성: `orchestrator/orchestrate.py`

discover→build→stream 흐름을 담당한다.

- `run_task`(단발 `str` 반환) → `run_task_stream(task, model=None,
  model_call_limit=5, recursion_limit=...)` async generator로 교체.
  `ProgressEvent`를 yield한다.
- discover 0개면 `final("No agents available.", truncated=False)` 단일 이벤트를
  yield하고 종료한다.
- `graph.astream(..., stream_mode="updates")`를 순회하며 `to_progress_event`로
  변환해 yield한다. 스트림 도중 예외는 잡아 `error` 이벤트로 yield한다.
- `build_orchestrator_graph`에 `StepLimitSynthesisMiddleware(model_call_limit)`을
  추가한다.
- 기존 `GraphRecursionError` try/except는 제거한다 (미들웨어가 대체).

### 재작성: `orchestrator/__main__.py`

CLI 인자 파싱을 제거하고 uvicorn으로 `orchestrator/server.py`의 앱을 기동한다
(`python -m orchestrator` → `127.0.0.1:9000` 서버 시작). `load_dotenv()` 유지.

### 유지 (변경 없음)

- `agent_tool.py` — 카드 → tool 변환 (원격 호출 실패 시 `"[error calling ...]"`
  문자열 반환은 그대로 두어 `tool_result` 이벤트로 관찰된다)
- `registry.py` — discover
- `client.py` — `call_agent`, `extract_response_text`
- `llm.py` — `message_content_to_text` (final 이벤트 content 추출에 재사용)

### 재사용하지 않음

- `common/server.py` — 에이전트용 A2A Starlette 서버다. 오케스트레이터 서버는
  A2A가 아닌 일반 HTTP라 책임이 다르므로 `orchestrator/server.py`를 별도로 둔다.

## 데이터 흐름

```
POST /run {task}
  → run_task_stream(task)
      → discover → build_orchestrator_graph(미들웨어 포함)
      → async for chunk in graph.astream({"messages":[user]},
                                          {"recursion_limit": N},
                                          stream_mode="updates"):
            event = to_progress_event(chunk)   # events.py
            if event: yield event              # orchestrate.py
  → server.py:  각 event → data: {...}\n\n
  → 마지막 final 이벤트 후 스트림 종료
```

이벤트 시퀀스 예시(정상): `tool_call(research)` → `tool_result(research)` →
`tool_call(summarizer)` → `tool_result(summarizer)` → `final(truncated=false)`.

강제 종합 예시: `tool_call` … (한도 도달) … → `final(truncated=true)`.

## 에러 처리

| 상황 | 처리 |
|------|------|
| discover 0개 | `final("No agents available.", truncated=false)` 단일 이벤트 후 종료 |
| 원격 에이전트 호출 실패 | (현행 유지) `agent_tool`이 예외를 잡아 `"[error calling ...]"` 반환 → `tool_result` 이벤트로 관찰 → LLM이 적응 |
| step limit 도달 | 미들웨어가 그래프 내부에서 강제 종합 → `final(truncated=true)`. `GraphRecursionError` 미발생 |
| 스트림 도중 예외 (LLM/네트워크 등) | `run_task_stream`이 잡아 `error` 이벤트(`{type:"error", message}`)로 yield 후 종료 → SSE가 끊기지 않고 클라이언트가 원인 인지 |
| 클라이언트 조기 연결 종료 | astream generator가 취소/GC됨. httpx AsyncClient는 `async with`로 자동 정리되므로 별도 정리 로직 불필요 |

**미들웨어 한도 vs recursion_limit:** 미들웨어의 `model_call_limit`이 실질
한도이고, `recursion_limit`은 그보다 넉넉한 안전망이다. 정상 경로에서
`GraphRecursionError`는 발생하지 않으므로 위 표에 recursion 항목이 없다.

## 테스트 전략

CLAUDE.md 테스트 규칙(given/when/then 주석, `it` 블록 내 리터럴, per-field
assert, 동작 기반 케이스명)을 준수한다.

| 대상 | 방식 |
|------|------|
| `events.to_progress_event` (tool_call) | `tool_calls`를 가진 `AIMessage` chunk 주입 → `tool_call` 이벤트, `agent`·`input` 검증 |
| `events.to_progress_event` (tool_result) | `ToolMessage` chunk 주입 → `tool_result` 이벤트, `agent`·`output` 검증 |
| `events.to_progress_event` (final) | tool_calls 없는 plain `AIMessage` chunk → `final` 이벤트, `content` 검증 |
| `events.to_progress_event` (무시 대상) | 이벤트로 매핑 안 되는 chunk → `None` 반환 검증 |
| `middleware` (한도 미도달) | 호출 횟수 < 한도 → tools 보존, override 미호출 검증 (fake handler 주입) |
| `middleware` (한도 도달) | 호출 횟수 = 한도-1 → tools 비워지고 종합 시스템 메시지 주입됨 검증 |
| `orchestrate.run_task_stream` (정상) | fake model이 tool_call → 최종 AIMessage 순서 반환 → yield 시퀀스가 `[tool_call, tool_result, final(truncated=false)]` 검증 |
| `orchestrate.run_task_stream` (강제 종합) | 한도를 낮춰 fake model이 계속 tool_call → 마지막에 `final(truncated=true)` 검증 |
| `orchestrate.run_task_stream` (에이전트 0개) | discover 빈 dict → `final("No agents available.")` 단일 이벤트 검증 |
| `server` (SSE 포맷) | fake `run_task_stream`을 주입한 starlette `TestClient` → `POST /run`이 `text/event-stream` 응답, body가 `data: {...}\n\n` 라인들로 구성됨 검증 |

**제거:** `test_orchestrate.py`의 기존 `run_task` 단발 반환 테스트(시그니처가
`run_task_stream`으로 바뀜).

**fake model 패턴(기존과 동일):** `FakeMessagesListChatModel`의 `responses`에
tool_calls를 가진 `AIMessage`들과 최종 `AIMessage`를 순서대로 넣어 ReAct 루프를
결정론적으로 구동한다. 미들웨어는 fake handler를 주입해 네트워크 없이 단위
테스트한다.

## 범위 밖 (확장 지점)

- 토큰 단위 스트리밍(`stream_mode="messages"`) — 현재는 스텝 단위로 충분
- 오케스트레이터 자신을 A2A 서버로 노출 (재귀적 위임)
- 멀티턴 컨텍스트(contextId) 유지
- 인증/레이트리밋 등 프로덕션 서버 관심사

## 기존 design 문서와의 관계

[2026-06-27-react-orchestrator-design.md](2026-06-27-react-orchestrator-design.md)의
"범위 밖" 절에 적힌 확장 지점 중 **"스트리밍 응답"**과 **"오케스트레이터를
서버로 노출"**을 이 문서가 구체화한다. 단, A2A `message/stream`이 아니라 일반
HTTP+SSE로 노출하기로 결정한 점이 다르다. ReAct 루프 구조·`agent_tool`·discover는
그대로 유효하다.
```
