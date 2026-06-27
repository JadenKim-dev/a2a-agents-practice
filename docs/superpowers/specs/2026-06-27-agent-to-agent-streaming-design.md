# 에이전트 간 통신 스트리밍 설계

작성일: 2026-06-27
관련: [[2026-06-27-react-orchestrator-design]], [[2026-06-27-orchestrator-sse-server-design]]

## 1. 목표

현재 오케스트레이터 자신의 진행(tool_call/tool_result/final)은 `POST /run`의 SSE로 실시간 스트리밍된다. 그러나 오케스트레이터가 호출하는 **서브 에이전트(Research, Summarizer)의 내부 툴 사용은 스트리밍되지 않는다.** 서브 에이전트는 `graph.ainvoke()`로 한 번에 실행되어 최종 텍스트만 반환하고, 오케스트레이터 클라이언트도 `streaming=False`로 받기 때문이다.

이 작업의 목표는 **서브 에이전트의 툴 호출/결과를 실시간으로 오케스트레이터까지 전달**하여, 소비자가 `POST /run` SSE 스트림에서 서브 에이전트의 진행까지 계층적으로 관찰할 수 있게 하는 것이다.

### 확정된 결정 (브레인스토밍)

- **세분화 수준**: 툴 호출/결과 단위 (LLM 토큰 단위 아님, 단계 요약 아님). 오케스트레이터가 자신에 대해 내보내는 tool_call/tool_result와 동일한 세분화.
- **이벤트 표현**: 계층 경로(`path`)로 구분. `ProgressEvent`에 `path: list[str]` 필드를 추가하고, 서브 에이전트 이벤트는 `path=["research"]`처럼 출처를 담는다. N단계 중첩으로 자연스럽게 확장 가능.
- **transport**: A2A 네이티브 스트리밍 사용. 서브 에이전트 서버는 `TaskStatusUpdateEvent`(`status_update`)로 중간 진행을 발행하고, 오케스트레이터 클라이언트는 `streaming=True`로 받아 파싱한다.
- **인코딩**: `status_update`의 `message.metadata`에 구조화 dict `{kind, agent, input, output}`를 싣고, `message.parts[0].text`에는 사람이 읽는 한 줄 요약을 둔다. extension URI 선언은 PoC 범위에서 생략.
- **호환성**: 스트리밍으로 전면 전환. executor는 항상 `astream`, 클라이언트는 항상 `streaming=True`. 비스트리밍 경로는 유지하지 않는다.

## 2. 표준 정합성 근거

A2A 명세에는 "에이전트의 툴 사용"을 위한 전용 타입이 없다. 명세가 정의하는 진행 전달 표준은 `TaskStatusUpdateEvent`(작업 진행 상태 + 중간 메시지)와 `TaskArtifactUpdateEvent`(산출물)뿐이며, `TaskStatus.message`에 "현재 단계를 설명하는 TextPart"를 담는 사람이 읽는 텍스트 수준을 예로 든다.

구조화된 커스텀 데이터의 표준 자리는 `metadata` 필드(`Message`, `Part`, `Task`, 이벤트의 key-value map)이고, 명세는 *"Extensions can be used to strongly type metadata values for specific use cases"*라고 권한다. 따라서 본 설계의 **"`status_update`의 metadata에 구조화 dict + text에 사람이 읽는 요약"** 방식은 표준 라인 위에 있다. extension URI 선언까지 가면 완전 정합이지만, PoC에서는 metadata dict만으로 충분하다고 판단했다.

이 방식의 이점:
- 표준 A2A 소비자는 `parts[0].text`만 읽어도 정상 동작한다(하위 호환).
- 우리 오케스트레이터는 `metadata`에서 정밀한 tool_call/tool_result를 복원한다.

검증: `Message(metadata={...})` dict 직접 주입과 왕복이 a2a-sdk 1.1.0에서 동작함을 확인했다. (`status.message.metadata`는 protobuf `Struct`로 변환되어 dict 왕복 가능.)

## 3. 데이터 흐름

```
서브 에이전트 graph.astream (tool_call / tool_result chunk)
  └─ LangGraphExecutor
       update_status(WORKING,
                     message=new_agent_message(parts=[Part(text=요약)]),
                     metadata={kind, agent, input | output})
         └─ A2A status_update (SSE)
              └─ 오케스트레이터 client (streaming=True)
                   status.message.metadata 파싱 → on_event(구조화 dict)
                     └─ agent_tool: 콜백 이벤트에 path=[이_에이전트명] 붙여 큐에 push
                          └─ orchestrate.run_task_stream
                               ReAct astream chunk + 서브 이벤트 큐를 시간순 병합
                                 └─ POST /run SSE → 소비자
```

## 4. 컴포넌트별 변경

### (a) `orchestrator/events.py` — `ProgressEvent`에 `path` 추가

- `path: list[str] | None = None` 필드 추가.
- 로컬 오케스트레이터 이벤트는 `path` 없음(`None`). 서브 에이전트 이벤트는 `["research"]` 등 출처 경로.
- 직렬화는 기존 `event_to_payload`(None 필드 제외)가 그대로 처리하므로 `path=None`이면 payload에서 빠진다.

### (b) `common/` — chunk 분류 순수 함수 공통화

서브 에이전트 graph와 오케스트레이터 graph 모두 LangGraph이므로 `astream(stream_mode="updates")` chunk 형태가 동일하다. 현재 `orchestrator/events.py`의 `_message_to_event`가 하는 "chunk/message → (kind, agent, input/output) 추출" 로직을 양쪽이 공유하도록 **순수 추출 함수 수준까지만** `common/`으로 옮긴다.

- 추출 결과는 프레임워크 중립적인 형태(예: `{kind, agent, input?, output?, content?, truncated?}` dict 또는 작은 dataclass).
- `orchestrator/events.py`는 이 추출 결과를 오케스트레이터 전용 `ProgressEvent`로 감싸고, `LangGraphExecutor`는 같은 추출 결과를 A2A `metadata`로 감싼다.
- `ProgressEvent` 자체는 오케스트레이터 전용 표현이므로 `common/`으로 옮기지 않는다.

### (c) `common/langgraph_executor.py` — `ainvoke` → `astream` 전환

가장 큰 변경. 서브 에이전트가 중간 진행을 발행하려면 graph를 스트리밍해야 한다.

- `graph.astream(state, stream_mode="updates")`로 chunk를 순회.
- 각 chunk를 (b)의 추출 함수로 분류:
  - `tool_call` / `tool_result` → `updater.update_status(TaskState.TASK_STATE_WORKING, message=new_agent_message(parts=[Part(text=요약)]), metadata={"kind":..., "agent":..., "input"|"output":...})`.
  - 최종 AI 메시지(텍스트) → 누적해 두었다가 마지막에 `updater.complete(message=new_agent_message(parts=[Part(text=최종)]))`.
- Task enqueue 선행 규칙(`new_task_from_user_message` → `enqueue_event(task)` → `TaskUpdater` → `start_work`)은 기존대로 유지.
- 요약 텍스트(`Part.text`)는 사람이 읽을 한 줄: 예) tool_call이면 `"calling {agent}: {input 일부}"`, tool_result면 `"{agent} returned: {output 일부}"`.

### (d) `orchestrator/client.py` — `streaming=True` + 콜백

- `ClientConfig(streaming=True)`.
- `call_agent(http, card, text, on_event=None)`: `status_update` 수신 시 `status.message.metadata`에서 구조화 dict를 꺼내 `on_event(dict)` 호출. `task`/`message`/`status_update`의 최종 텍스트는 기존처럼 회수해 반환값으로 유지.
- 기존 `extract_response_text`는 최종 텍스트용으로 유지. 신규 `extract_progress_metadata(status_update) -> dict | None` 추가.
- metadata가 없거나 우리 스키마(`kind` 키)가 아니면 `on_event`를 호출하지 않고 무시(표준/구버전 에이전트 관대 처리).

### (e) `orchestrator/agent_tool.py` — 콜백으로 서브 이벤트 방출

tool 함수는 문자열만 반환하고 ReAct astream chunk에는 서브 에이전트 내부 이벤트가 담기지 않는다. 따라서 서브 이벤트는 tool 실행 중 콜백으로 외부 큐에 밀어넣는다.

- `build_agent_tool`에 이벤트 싱크(콜백 또는 큐)를 주입.
- tool 실행 시 `call_agent(..., on_event=lambda meta: sink(ProgressEvent(type=meta["kind"], agent=meta.get("agent"), input=meta.get("input"), output=meta.get("output"), path=[name])))`.
- 콜백/싱크 예외는 흡수해 ReAct 루프를 멈추지 않는다(기존 `[error calling ...]` 패턴과 일관).

### (f) `orchestrator/orchestrate.py` — ReAct chunk + 서브 이벤트 큐 병합

- `asyncio.Queue`를 만들어 agent_tool 싱크가 서브 이벤트를 push.
- `run_task_stream`은 graph.astream과 큐 두 소스를 동시에 소비해 **시간순으로 yield**한다.
- graph.astream이 끝나면 큐에 sentinel을 넣어 병합 루프를 종료하고, 남은 서브 이벤트를 drain한 뒤 종료(유실 방지).
- 기존 try/except(스트림 무중단, `error_event`) 유지.

## 5. 에러 처리

- **서브 graph 실패**: executor 내 try/except 유지 → `updater.failed(...)`. astream 도중 예외도 동일 처리.
- **status_update 파싱 실패/비표준**: metadata 없거나 `kind` 없으면 콜백 건너뜀(무시). 표준 소비자/구버전 호환.
- **콜백/큐 예외 격리**: agent_tool 싱크 예외 흡수 → ReAct 루프 무중단.
- **병합 종료**: sentinel + drain으로 서브 이벤트 유실 방지.

## 6. 테스트 전략

기존 `tests/` 구조와 결정론 규칙(OpenAI/Tavily 가짜 대체)을 따른다. 각 케이스는 given/when/then 주석, 입력 리터럴을 `it` 내부에 둔다.

- **`test_langgraph_executor.py`**: 가짜 graph가 `astream`으로 tool_call/tool_result chunk를 낼 때 executor가 `update_status`를 (kind/agent/input/output metadata와 함께) 올바른 순서·횟수로 호출하고 마지막에 `complete`를 호출하는지. graph 예외 시 `failed` 호출.
- **`test_client.py`**(신규): 가짜 A2A 스트림이 metadata 포함 `status_update`를 낼 때 `on_event`가 구조화 dict로 호출되고 최종 텍스트 반환이 유지되는지. metadata 없는 status_update는 콜백 미호출.
- **`test_agent_tool.py`**: 싱크가 `path`를 붙여 이벤트를 push하는지, 서브 호출 예외가 흡수되는지.
- **`test_orchestrate.py`**: ReAct chunk와 서브 이벤트 큐가 시간순 병합되어 yield되고 서브 이벤트에 `path`가 실리는지. sentinel 종료/drain.
- **`test_events.py`**: `ProgressEvent.path` 직렬화(None이면 제외, 있으면 포함).
- **`test_server.py` / `test_orchestrator_server.py`**: SSE payload에 `path`가 한글 비이스케이프(`ensure_ascii=False`)로 실리는지(회귀 포함).

## 7. 범위 밖 (out of scope)

- LLM 토큰 단위 스트리밍.
- extension URI 선언 및 카드 capabilities.extensions 등록.
- 3단계 이상 실제 중첩 시나리오(설계는 `path` 리스트로 확장 가능하나 PoC 시나리오는 2단계).
- cancel/푸시 알림.
