# agentgateway를 A2A 에이전트 앞단 프록시로 두기 (PoC)

작성일: 2026-06-28
관련: [[2026-06-24-a2a-multi-agent-orchestration-design]]

## 1. 목표

오픈소스 [agentgateway](https://agentgateway.dev)(Linux Foundation 프로젝트, Solo.io 발, Rust 구현)를
이 PoC의 A2A 에이전트 앞단에 프록시로 끼워, **게이트웨이가 우리 a2a-sdk 1.1.0 에이전트의
호출을 투명하게 프록시하는지** 검증한다.

agentgateway는 MCP/A2A/LLM을 위한 agentic proxy로, `a2a: {}` 정책을 라우트에 붙이면
백엔드 A2A 서버 앞단에서 카드 discovery와 메시지 호출을 중계한다. 이 PoC의 질문은 단 하나다:

> 기존 오케스트레이터 → 에이전트 end-to-end 흐름이, 게이트웨이를 끼운 상태에서 깨지지 않는가?

부가 가치(인증/rate limit/관측성)는 "프록시가 우리 호출을 깨지 않는다"를 먼저 증명한 뒤의 일이며,
이번 범위는 **순수 패스스루**다.

### 확정된 결정 (브레인스토밍)

- **게이트웨이 위치**: 에이전트 앞단 프록시. 오케스트레이터(:9000)가 백엔드를 직접 부르지 않고
  게이트웨이를 통해 호출한다.
- **매핑 방식 (접근 B)**: 에이전트당 게이트웨이 bind 1개로 **포트 1:1 매핑**.
  `:8001 → :9001`(research), `:8002 → :9002`(summarizer). 경로 기반 라우팅(접근 A)은 다음 단계.
- **카드 URL 처리**: 카드의 광고 URL을 **환경변수로 외부화**한다. 게이트웨이를 우회하지 않도록,
  게이트웨이 모드에서는 카드가 게이트웨이 주소를 광고하게 한다. (게이트웨이가 카드 body를
  rewrite하는 방식은 agentgateway 지원 여부가 불확실하므로, 우리 통제 안에 있는 환경변수 외부화를 택함.)
- **하위호환**: 환경변수 미설정 시 기존 `127.0.0.1:9001/9002`를 기본값으로 유지 → 게이트웨이 없이
  직접 실행하는 기존 흐름이 그대로 동작한다.

## 2. 왜 카드 URL이 핵심인가

우리 에이전트 카드는 자기 URL을 `supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=...)]`에
박아 광고한다(`common/agent_card.py`). 클라이언트는 `ClientFactory.create(card)`로 만든 뒤
**카드 안의 url을 실제 메시지 호출 목적지로 사용**한다.

따라서 카드의 url이 백엔드 직접 주소(`http://127.0.0.1:9001/`)인 채로 게이트웨이를 통해 카드를 받아도,
이어지는 `message/send`는 카드 안 url을 보고 **백엔드로 직행**해 게이트웨이를 우회한다.
진짜 프록시가 되려면 카드가 게이트웨이 주소(`http://127.0.0.1:8001/`)를 광고해야 한다.

현재 url은 `agents/research/card.py`의 `RESEARCH_URL = "http://127.0.0.1:9001/"`처럼 하드코딩이다.
이를 환경변수로 외부화한다.

## 3. 데이터 흐름

```
오케스트레이터(:9000)
   │  discover_agents (카드 GET) → call_agent (message/send, streaming)
   ▼
agentgateway (한 프로세스, bind 2개, policies: a2a {})
   :8001 ─────────────▶ research 백엔드   127.0.0.1:9001
   :8002 ─────────────▶ summarizer 백엔드 127.0.0.1:9002
```

- 오케스트레이터의 `AGENT_URLS`를 게이트웨이 포트로 교체 → discovery·메시지 호출이 모두 게이트웨이 통과.
- research 백엔드는 `RESEARCH_PUBLIC_URL=http://127.0.0.1:8001/`로 기동 → 카드가 게이트웨이 주소를 광고.
- summarizer도 동일하게 `SUMMARIZER_PUBLIC_URL=http://127.0.0.1:8002/`.

## 4. 컴포넌트별 변경

### (a) `common/agent_card.py` — 변경 없음

`build_agent_card(url=...)`는 이미 url을 인자로 받는다. 호출부에서 환경변수를 읽어 넘기면 된다.

### (b) `agents/research/card.py`, `agents/summarizer/card.py` — 광고 URL을 환경변수로

```python
import os
RESEARCH_URL = os.environ.get("RESEARCH_PUBLIC_URL", "http://127.0.0.1:9001/")
```

- 환경변수명: `RESEARCH_PUBLIC_URL`, `SUMMARIZER_PUBLIC_URL`.
- 미설정 시 기존 백엔드 주소를 기본값으로 → 하위호환.
- **bind 포트(9001/9002)와 광고 url은 별개**다. 서버는 여전히 `127.0.0.1:9001`에 바인딩하고,
  카드가 광고하는 url만 게이트웨이 주소로 바뀐다. (`__main__.py`의 `port=9001`은 그대로 둔다.)

### (c) `orchestrator/registry.py` — `AGENT_URLS`를 환경변수로

```python
AGENT_URLS = {
    "research": os.environ.get("RESEARCH_AGENT_URL", "http://127.0.0.1:9001"),
    "summarizer": os.environ.get("SUMMARIZER_AGENT_URL", "http://127.0.0.1:9002"),
}
```

- 게이트웨이 모드: `RESEARCH_AGENT_URL=http://127.0.0.1:8001` 등을 주입.
- 미설정 시 기존 백엔드 주소 → 하위호환.

### (d) agentgateway config — `config/agentgateway.yaml` (신규)

```yaml
binds:
  - port: 8001
    listeners:
      - routes:
          - policies:
              a2a: {}
            backends:
              - host: 127.0.0.1:9001
  - port: 8002
    listeners:
      - routes:
          - policies:
              a2a: {}
            backends:
              - host: 127.0.0.1:9002
```

카드 경로(`/.well-known/agent-card.json`)와 JSON-RPC 경로(`/`)가 이 패스스루를 그대로 통과하는지가
검증 대상이다.

### (e) 기동 스크립트 — `scripts/run_gateway.sh` (신규)

게이트웨이를 끼운 전체 스택을 한 번에 띄우는 편의 스크립트. 두 종류의 환경변수가 각기 다른 프로세스에 주입된다:

- `RESEARCH_PUBLIC_URL` / `SUMMARIZER_PUBLIC_URL` → **백엔드 프로세스**(카드가 광고할 게이트웨이 주소).
- `RESEARCH_AGENT_URL` / `SUMMARIZER_AGENT_URL` → **오케스트레이터 프로세스**(호출 목적지인 게이트웨이 주소).

스크립트는 백엔드 2개를 `*_PUBLIC_URL`과 함께 기동하고, agentgateway를 위 config로 띄운 뒤,
오케스트레이터는 `*_AGENT_URL`과 함께 기동한다. (게이트웨이 바이너리 설치는 수동 가정 — README에 안내.)

## 5. 검증

기존 흐름을 게이트웨이를 끼운 상태에서 돌려 end-to-end가 깨지지 않는지 확인한다.

1. **카드 discovery 통과 + url 광고 확인**
   `curl :8001/.well-known/agent-card.json` → 카드가 게이트웨이를 통해 반환되고,
   카드 안 `supported_interfaces[].url`이 `http://127.0.0.1:8001/`인지.
2. **오케스트레이터 end-to-end**
   `AGENT_URLS`를 게이트웨이 포트로 둔 채 `POST :9000/run` → research/summarizer가 게이트웨이를
   거쳐 호출되고 SSE 최종 답변이 정상적으로 나오는지.
3. **스트리밍 중간 이벤트 통과**
   서브 에이전트의 `status_update`(진행 이벤트)가 게이트웨이를 통과해 오케스트레이터까지 도달하는지.
   메모리의 "양쪽 AND 스트리밍 게이트"에 더해, **게이트웨이가 SSE를 버퍼링하지 않는지**가 위험 포인트다.
   중간 이벤트가 0개로 떨어지면 게이트웨이의 버퍼링/프록시 모드를 의심한다.

검증은 수동 + 가능하면 in-process 통합 테스트로 보강한다. 단, agentgateway는 외부 바이너리이므로
CI에 묶기보다 **로컬 수동 검증 + 절차 문서화**를 우선한다.

## 6. 범위 밖 (YAGNI)

- **인증/인가, rate limit, 관측성(metric/trace)** — 게이트웨이의 부가 가치지만 패스스루 검증 후의 일.
- **경로 기반 단일 엔드포인트 라우팅(접근 A)** — 다음 단계.
- **게이트웨이 바이너리 설치 자동화** — 수동 설치 가정, README 안내만.
- **게이트웨이 config의 CORS/TLS** — 로컬 PoC에 불필요.
- **카드 body rewrite를 게이트웨이에 맡기는 방식** — 지원 불확실. 환경변수 외부화로 우회.

## 7. 리스크와 미지수

- **A2A 전송 호환성**: agentgateway의 `a2a: {}` 정책이 a2a-sdk 1.1.0 JSONRPC 바인딩(카드 + JSON-RPC `message/send`)을
  깨지 않고 중계하는지는 실제로 돌려봐야 안다. 이게 PoC의 본질적 미지수다.
- **SSE 버퍼링**: 게이트웨이가 스트리밍 응답을 버퍼링하면 중간 진행 이벤트가 사라진다. 검증 3번이 이를 잡는다.
- **카드 url ↔ bind 포트 분리**: 광고 url과 실제 bind 포트를 헷갈리면 게이트웨이 우회/연결 실패가 난다.
  설계상 둘을 명시적으로 분리(4-b)해 이 혼동을 차단한다.

## 8. 검증 결과 (2026-06-28)

실제 agentgateway 바이너리로 전체 스택을 띄워 §5의 검증 3종을 모두 수행했고, **세 미지수가 모두 해소**됐다.

**환경**
- agentgateway **v1.3.1** (GitHub release `agentgateway-darwin-arm64`, sha256 검증 후 `~/.local/bin`에 설치).
- config 플래그는 `-f`(스크립트와 일치). `--validate-only`로 우리 `config/agentgateway.yaml`이
  v1.3.1 스키마에서 "Configuration is valid!" 확인.
- 실제 OpenAI/Tavily 키로 research(웹검색)→summarizer 흐름을 실행.

**검증 1 — 카드 discovery 통과 + url 광고: ✅**
- `curl :8001/.well-known/agent-card.json` → `supportedInterfaces[0].url == http://127.0.0.1:8001/`
  (백엔드는 9001에 바인딩하지만 카드는 게이트웨이 주소를 광고 — Task 1 환경변수 외부화가 실제로 동작).
- `:8002`(summarizer)도 동일하게 게이트웨이 주소 광고.
- 게이트웨이 로그: `http.path=/.well-known/agent-card.json ... endpoint=127.0.0.1:9001 http.status=200 protocol=a2a`.

**검증 2 — 오케스트레이터 end-to-end: ✅**
- 오케스트레이터를 `RESEARCH_AGENT_URL/SUMMARIZER_AGENT_URL`을 게이트웨이 포트로 둔 채 기동,
  `POST :9000/run`이 `tool_call`→`tool_result`→`final` SSE를 정상 반환. discovery skip·에러 없음.
- 게이트웨이 로그 결정타:
  `http.method=POST http.path=/ protocol=a2a a2a.method=SendStreamingMessage http.status=200 duration=12236ms`
  — agentgateway가 A2A 프로토콜과 `SendStreamingMessage`를 인지하고 12초짜리 스트리밍 요청을 깨지 않고 중계.

**검증 3 — 스트리밍 중간 이벤트 통과(버퍼링 없음): ✅**
- 한 `/run` 응답의 이벤트 도착 타임라인(초): 16(research tool_call) → 17(`tavily_search` tool_call,
  `path:["research"]`) → 21(tavily tool_result) → 28(research tool_result) → 32(final).
- 서브 에이전트의 `status_update`(=`path:["research"]` 이벤트)가 게이트웨이를 통과했고, 이벤트가
  **마지막에 몰리지 않고 점진적으로 도착** — 게이트웨이의 SSE 버퍼링 없음.

**결론**: 접근 B(포트 1:1 패스스루)에서 agentgateway는 a2a-sdk 1.1.0의 카드 discovery,
JSON-RPC 스트리밍 `message/send`, SSE 중간 이벤트를 모두 투명하게 중계한다. 카드 url 외부화만으로
오케스트레이터 코드 변경 없이 게이트웨이를 끼울 수 있음을 확인했다. 다음 단계인 접근 A(경로 라우팅)와
부가 정책(인증/rate limit/관측성)은 이 패스스루 기반 위에서 진행 가능하다.
