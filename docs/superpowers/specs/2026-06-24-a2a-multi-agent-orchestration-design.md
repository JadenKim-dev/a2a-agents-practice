# A2A 멀티 에이전트 오케스트레이션 PoC — 설계

작성일: 2026-06-24

## 목표

개별 에이전트를 독립 서버로 띄우고, 이들이 Google A2A(Agent2Agent) 공식
프로토콜로 통신하며, Orchestration Agent가 LLM 기반 동적 라우팅으로 이들을
조합해 종합 과업을 수행하는 구조를 만든다.

1차 목표는 **동작하는 최소 PoC**다: 에이전트 2개(Research, Summarizer) +
오케스트레이터 1개가 실제 A2A 메시지로 통신하며 "리서치 → 요약" 파이프라인을
끝까지 수행한다.

## 기술 선택

| 영역 | 선택 | 이유 |
|------|------|------|
| 통신 프로토콜 | Google A2A 공식 표준 (`a2a-sdk`) | 외부 에이전트와의 상호운용·표준 준수 |
| 에이전트 내부 두뇌 | LangGraph + OpenAI (`langchain-openai`) | 노드/엣지 그래프로 내부 추론·툴 체이닝 구성 |
| 오케스트레이션 | LLM 기반 동적 라우팅 | Agent Card를 근거로 매 과업마다 호출 계획을 LLM이 결정 |
| 언어 | Python | A2A/LLM 생태계 SDK가 가장 풍부 |
| ASGI 서버 | uvicorn | A2A SDK가 Starlette 앱을 노출 |

## 아키텍처

각 에이전트는 독립 HTTP 서버로 뜨고, 자신을 설명하는 Agent Card를
`/.well-known/agent-card.json`에 노출한다. 오케스트레이터는 A2A 클라이언트로서
이 카드들을 읽어 각 에이전트의 능력을 파악하고, LLM으로 호출 계획을 세운 뒤
A2A 메시지(JSON-RPC over HTTP)로 위임한다.

```
                    ┌─────────────────────────────┐
   사용자 과업 ───▶  │   Orchestrator Agent         │
                    │   (A2A Client + LangGraph)   │
                    │   - Agent Card discovery      │
                    │   - LLM 동적 라우팅            │
                    │   - 결과 종합                 │
                    └──────┬───────────────┬───────┘
                           │ A2A           │ A2A
                  (JSON-RPC over HTTP)  (JSON-RPC over HTTP)
                           ▼               ▼
              ┌──────────────────┐  ┌──────────────────┐
              │ Research Agent   │  │ Summarizer Agent │
              │ (A2A Server)     │  │ (A2A Server)     │
              │  :9001           │  │  :9002           │
              │ LangGraph+OpenAI │  │ LangGraph+OpenAI │
              │  + 검색 툴        │  │  (요약)           │
              └──────────────────┘  └──────────────────┘
```

### 핵심 흐름 (리서치 + 요약 파이프라인)

1. 사용자가 오케스트레이터에 과업 전달
   (예: "양자컴퓨팅의 최신 동향을 조사해서 3문단으로 요약해줘").
2. 오케스트레이터가 두 에이전트의 Agent Card를 읽고, LLM이
   "먼저 Research, 그 결과를 Summarizer로" 계획을 세운다.
3. Research Agent에 A2A 메시지 전송 → LangGraph가 검색 툴을 돌려 자료 수집
   → 결과 반환.
4. 그 결과를 Summarizer Agent에 A2A 메시지로 전달 → 요약 반환.
5. 오케스트레이터가 최종 종합 후 사용자에게 응답.

## 디렉토리 구조

PoC지만 "에이전트를 쉽게 추가할 수 있는" 형태로 잡는다. 공통 코드는 한 번만
작성하고, 새 에이전트는 LangGraph 그래프와 Agent Card 두 가지만 정의하면
되도록 한다.

```
a2a_agents/
├── pyproject.toml              # a2a-sdk, langgraph, langchain-openai, uvicorn, httpx
├── .env.example                # OPENAI_API_KEY 등
├── README.md
│
├── common/                     # 모든 에이전트가 공유하는 추상화
│   ├── __init__.py
│   ├── langgraph_executor.py   # LangGraph 그래프를 A2A AgentExecutor로 감싸는 어댑터
│   └── server.py               # AgentCard + Executor → uvicorn 서버 기동 헬퍼
│
├── agents/
│   ├── research/
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph: OpenAI + 검색 툴로 자료 조사
│   │   ├── card.py             # 이 에이전트의 AgentCard (skills 정의)
│   │   └── __main__.py         # `python -m agents.research` → :9001 기동
│   │
│   └── summarizer/
│       ├── __init__.py
│       ├── graph.py            # LangGraph: 입력 텍스트를 요약
│       ├── card.py
│       └── __main__.py         # `python -m agents.summarizer` → :9002 기동
│
├── orchestrator/
│   ├── __init__.py
│   ├── registry.py             # 알려진 에이전트 URL 목록 → Agent Card discovery
│   ├── client.py               # A2AClient 래퍼: 원격 에이전트에 메시지 전송
│   ├── graph.py                # LangGraph: LLM이 호출 대상·순서를 동적 라우팅
│   └── __main__.py             # CLI: 과업 입력받아 실행
│
└── scripts/
    └── run_all.sh              # 에이전트 2개 + (선택) 오케스트레이터 함께 기동
```

### 각 단위의 책임

| 단위 | 책임 | 의존 |
|------|------|------|
| `common/langgraph_executor.py` | LangGraph 그래프 하나를 받아 A2A `AgentExecutor.execute()`로 변환 (메시지 in → 그래프 실행 → 결과를 EventQueue로) | a2a-sdk, langgraph |
| `common/server.py` | AgentCard + Executor를 받아 `A2AStarletteApplication` + uvicorn 기동 | a2a-sdk |
| `agents/*/graph.py` | 그 에이전트만의 LangGraph 추론 로직 | langgraph, langchain-openai |
| `agents/*/card.py` | 그 에이전트의 능력 선언 (AgentCard/AgentSkill) | a2a-sdk |
| `orchestrator/registry.py` | 에이전트 URL → Agent Card 가져오기(discovery) | a2a-sdk client |
| `orchestrator/client.py` | 특정 에이전트에 A2A 메시지 보내고 결과 받기 | a2a-sdk client |
| `orchestrator/graph.py` | LLM 기반 라우팅: 카드 보고 호출 순서 결정 + 결과 종합 | langgraph |

**설계 의도:** 새 에이전트 추가 = `agents/<name>/`에 `graph.py` + `card.py` +
`__main__.py` 3개만 작성. 공통 서버/어댑터 코드는 재사용. 오케스트레이터는
`registry.py`의 URL 목록에 한 줄 추가하면 새 에이전트를 자동 인식한다.

## 데이터 흐름 & 오케스트레이션 메커니즘

### A. 에이전트 서버 측 (Research / Summarizer 공통)

A2A 프로토콜은 `message/send`(동기) / `message/stream`(스트리밍) RPC를 받는다.
PoC는 동기(`message/send`)로 시작한다.

```
A2A 메시지 도착
  → AgentExecutor.execute(context, event_queue)
      → context에서 사용자 텍스트 추출
      → LangGraph 그래프 invoke (OpenAI 호출 / 툴 실행)
      → 최종 텍스트를 event_queue로 enqueue (Task 완료 이벤트)
  → A2A SDK가 JSON-RPC 응답으로 직렬화해 클라이언트에 반환
```

`common/langgraph_executor.py`가 이 변환을 담당한다. 모든 에이전트가 동일
어댑터를 공유하고, 차이는 주입되는 그래프뿐이다.

### B. 오케스트레이터 측 (LLM 동적 라우팅)

```
사용자 과업
  → [discovery] registry가 각 에이전트 URL의 Agent Card 수집
        (이름/설명/skills를 LLM 컨텍스트용 텍스트로 변환)
  → [planning] LangGraph 노드: LLM에게
        "다음 에이전트들이 있다: {카드 요약}. 이 과업을 위해 누구를
         어떤 순서로 호출할지, 각자에게 보낼 입력은?" 질의
        → 구조화된 호출 계획 산출 (예: [research(query), summarize(그 결과)])
  → [execution] 계획대로 client가 각 에이전트에 A2A 메시지 전송
        (이전 단계 출력을 다음 단계 입력으로 연결)
  → [synthesis] LangGraph 노드: LLM이 수집된 결과를 최종 답변으로 종합
  → 사용자에게 반환
```

**라우팅을 동적으로 만드는 부분:** 호출 순서·대상·각 에이전트로 보낼 입력
문구를 코드가 하드코딩하지 않고, LLM이 Agent Card를 근거로 매 과업마다
결정한다. 그래서 나중에 에이전트를 추가해도 오케스트레이터 코드 수정 없이
(registry URL만 추가) LLM이 새 능력을 고려한다.

### C. 에러 처리 (PoC 수준)

| 상황 | 처리 |
|------|------|
| 에이전트 서버 다운/연결 실패 | discovery 시 해당 카드 skip + 경고 로그. 실행 중이면 "해당 에이전트 호출 실패"를 LLM 종합 단계에 전달 |
| LangGraph/OpenAI 예외 | execute 내에서 잡아 Task를 `failed` 상태 + 에러 메시지로 반환 (서버 무중단) |
| LLM이 잘못된 계획 산출 (없는 에이전트 호출) | 계획 검증 단계에서 registry에 없는 이름은 필터링 + 경고 |
| 무한 위임 루프 | 오케스트레이터에 최대 호출 횟수(예: 5) 가드 |

## 테스트 전략 (PoC 수준, 핵심 경로 중심)

| 레벨 | 대상 | 방식 |
|------|------|------|
| 단위 | `agents/*/graph.py` | LangGraph 그래프를 직접 invoke — OpenAI는 가짜 모델로 대체해 입력→출력 형태 검증 (네트워크/비용 없음) |
| 단위 | `orchestrator/graph.py` 라우팅 | 가짜 Agent Card 목록 + 가짜 LLM 응답 주입 → 올바른 호출 계획 산출 검증 |
| 통합 | `common/langgraph_executor.py` | 인메모리로 Executor에 메시지 넣고 EventQueue 출력 확인 (A2A 서버 미기동) |
| E2E (수동) | 전체 | `run_all.sh`로 서버 띄우고 실제 과업 한 건 수행 후 확인 |

자동 테스트는 LLM 호출을 가짜로 대체해 결정론적으로 만든다(실제 OpenAI
호출은 E2E 수동 확인에서만). 각 테스트 케이스는 given→when→then이 자명하도록
입력 조건을 `it` 블록 내 리터럴로 둔다.

## 실행 방법

```bash
# 1. 의존성 설치
uv sync            # 또는 pip install -e .

# 2. 환경변수
cp .env.example .env   # OPENAI_API_KEY 채우기

# 3. 에이전트 서버들 기동 (각각 별도 터미널 또는 run_all.sh)
python -m agents.research      # :9001
python -m agents.summarizer    # :9002

# 4. 오케스트레이터로 과업 실행
python -m orchestrator "양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"
```

각 에이전트 서버는 독립적으로 떠 있으므로 기동 후
`http://localhost:9001/.well-known/agent-card.json`을 직접 확인해 Agent Card
노출을 검증할 수 있다.

## 범위 밖 (확장 지점)

YAGNI 원칙으로 PoC에서는 제외하고, 확장 지점으로만 표시한다.

- 스트리밍 응답 (`message/stream`)
- Agent Card 인증(auth) / 보안
- 멀티턴 컨텍스트(contextId) 유지
- 재시도/백오프, 서킷 브레이커
- 에이전트 동적 등록(현재는 registry에 URL 하드코딩)

## 구현 시 주의점 (의존성 버전)

`a2a-sdk`는 버전에 따라 API(`AgentExecutor` 시그니처, import 경로, AgentCard
필드명)가 바뀌어 왔다. 따라서 **구현 첫 태스크에서 설치된 `a2a-sdk` 버전을
고정(pin)하고 실제 import 경로·시그니처를 검증**한 뒤 나머지를 진행한다.
설계의 코드 패턴은 현재 안정 버전 기준이며, 검증 결과에 맞춰 조정한다.
