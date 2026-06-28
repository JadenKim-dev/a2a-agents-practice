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
- **매핑 방식 (접근 B → 접근 A로 전환)**: 처음엔 에이전트당 게이트웨이 bind 1개로 **포트 1:1 매핑**
  (`:8001 → :9001` research, `:8002 → :9002` summarizer)을 검증했고(§8), 이후 **단일 포트 + 경로 기반
  라우팅(접근 A)**으로 전환했다(§9). 현재 config/스크립트는 접근 A 기준이며, 접근 B는 git history와
  본 문서 §8에 검증 기록으로 남는다.
- **카드 URL 처리**: 카드의 광고 URL을 **환경변수로 외부화**한다. 게이트웨이를 우회하지 않도록,
  게이트웨이 모드에서는 카드가 게이트웨이 주소를 광고하게 한다. (게이트웨이의 카드 url rewrite는
  우리 SDK가 쓰는 필드를 건드리지 못해 단독으로는 우회를 막지 못한다 — §7-A에서 실증. 그래서
  우리 통제 안에 있는 환경변수 외부화를 택함.)
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
- **경로 기반 단일 엔드포인트 라우팅(접근 A)** — 완료(§9).
- **게이트웨이 바이너리 설치 자동화** — 수동 설치 가정, README 안내만.
- **게이트웨이 config의 CORS/TLS** — 로컬 PoC에 불필요.
- **카드 body rewrite를 게이트웨이에 맡기는 방식** — agentgateway가 rewrite 기능을 제공하긴 하나
  우리 SDK가 쓰는 필드(`supportedInterfaces[].url`)는 건드리지 못한다(§7-A 실증). 환경변수 외부화로 우회.

## 7. 리스크와 미지수

- **A2A 전송 호환성**: agentgateway의 `a2a: {}` 정책이 a2a-sdk 1.1.0 JSONRPC 바인딩(카드 + JSON-RPC `message/send`)을
  깨지 않고 중계하는지는 실제로 돌려봐야 안다. 이게 PoC의 본질적 미지수다.
- **SSE 버퍼링**: 게이트웨이가 스트리밍 응답을 버퍼링하면 중간 진행 이벤트가 사라진다. 검증 3번이 이를 잡는다.
- **카드 url ↔ bind 포트 분리**: 광고 url과 실제 bind 포트를 헷갈리면 게이트웨이 우회/연결 실패가 난다.
  설계상 둘을 명시적으로 분리(4-b)해 이 혼동을 차단한다.

### 7-A. 게이트웨이 카드 url rewrite는 우리 SDK에 충분하지 않다 (실증, 2026-06-28)

"에이전트 카드는 에이전트 소유물이므로 게이트웨이 주소를 에이전트가 광고하는 건 계층 침범이다.
rewrite는 게이트웨이가 해야 깔끔하다"는 지적이 구조적으로 옳다. agentgateway도 실제로
**카드 url rewrite 기능을 제공한다**(공식 문서: "Rewrites agent card URLs so they point to the gateway").
그래서 환경변수 외부화 대신 게이트웨이 rewrite에 맡길 수 있는지 실증했다.

`*_PUBLIC_URL` 없이 백엔드를 띄우고(카드는 기본값 `:9001/` 광고) 게이트웨이(:8001)를 통해 카드를 받은 결과:

| 카드 필드 | 게이트웨이 rewrite | a2a-sdk 1.1.0이 호출 목적지로 사용? |
|---|---|---|
| top-level `url` (구식 A2A 0.2 스키마) | ✅ `:9001` → `:8001` | ❌ `card.url`이 `None`으로 파싱되어 무시됨 |
| `supportedInterfaces[].url` (protobuf 0.3 스키마) | ❌ 그대로 통과(`:9001/`) | ✅ `ClientFactory`가 이 필드로 transport 선택 |

즉 게이트웨이 rewrite는 **구식 top-level `url`만** 안다. 우리 a2a-sdk 1.1.0은 protobuf 기반
`supportedInterfaces`를 쓰는데 게이트웨이가 이 필드를 모르므로, rewrite에만 의존하면 클라이언트는
백엔드(`:9001`)로 **직행해 게이트웨이를 우회**한다. 검증 로그: 게이트웨이 경유 카드를
`A2ACardResolver`로 파싱하니 `card.url == None`, `supported_interfaces == [('http://127.0.0.1:9001/', 'JSONRPC')]`.

**결론**: 환경변수 외부화(`*_PUBLIC_URL`)는 임시 우회가 아니라 **이 SDK 버전에서 카드가 게이트웨이
주소를 광고하게 하는 유일한 방법**이다. 게이트웨이 rewrite로 대체하려면 SDK가 top-level `url`을
호출 목적지로 인식하는 버전이거나, 게이트웨이가 `supportedInterfaces[].url`까지 rewrite해야 한다 —
둘 다 우리가 테스트한 v1.3.1에서는 성립하지 않는다.

#### upstream 추적: 이 한계는 v1.3.1의 버그였고 이미 수정됨 (미출시)

이 rewrite 한계로 별도 이슈가 등록된 적은 없으나, agentgateway가 PR로 직접 인지·수정했다 —
[agentgateway#2251 "Support A2A v1.0 agent card format in URL rewriting"](https://github.com/agentgateway/agentgateway/pull/2251)
(머지 2026-06-24, commit `c86dc1692`, `crates/agentgateway/src/a2a/mod.rs`). PR 본문이 우리 실측과 정확히 일치한다:

> "A2A v1.0 removed the top-level `url` field from AgentCard and replaced it with a `supportedInterfaces` array
> where each AgentInterface carries its own `url`. The gateway's `apply_to_response` **previously bailed with
> 'agent card missing URL' on any v1.0 response**." → 수정 후 v1.0(`supportedInterfaces`)은 각 interface entry의
> url을 rewrite, v0.3(`url`)은 기존 동작 유지.

타임라인이 우리 실증이 옳았음을 뒷받침한다:

| 시점 | 사건 |
|---|---|
| 2026-06-22 | **v1.3.1 릴리스** — 우리가 설치/테스트한 버전 (수정 전, `supportedInterfaces` rewrite 미지원) |
| 2026-06-24 | **PR #2251 머지** — `supportedInterfaces[].url` rewrite 추가 |
| 2026-06-28(현재) | v1.3.1이 여전히 Latest. PR #2251 포함 릴리스는 **아직 미출시** |

→ 우리가 겪은 건 v1.3.1의 실제 버그였고 이틀 뒤 고쳐졌으나, 아직 릴리스 바이너리에는 안 들어갔다.
**지금 당장은 `*_PUBLIC_URL` 외부화가 여전히 옳고 필요하다.** 다만 PR #2251을 포함한 릴리스(v1.3.2/v1.4.x 등)가
나오면 게이트웨이가 `supportedInterfaces[].url`까지 rewrite하므로, 그때는 §확정된 결정의 "카드 URL 처리"를
재검토해 **`*_PUBLIC_URL`과 `card.py`의 url 외부화를 제거하고 게이트웨이 rewrite에 맡기는 더 깔끔한 구조로
전환 가능**하다. 이는 "에이전트는 게이트웨이를 몰라야 한다"는 계층 분리 원칙에도 부합한다 — 다음 단계의 검토 항목.

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

## 9. 접근 A — 단일 포트 + 경로 기반 라우팅

접근 B(에이전트당 포트)를 **단일 게이트웨이 포트(:8080) + path prefix 라우팅**으로 전환한다.
프로덕션에서는 게이트웨이를 에이전트마다 포트로 늘리기보다 **하나의 진입점 뒤에 경로로 분기**하는
형태가 더 현실적이며, 인증·rate limit 같은 부가 정책도 단일 진입점에 거는 편이 운영상 자연스럽다.

### 9-A. 핵심: a2a-sdk와 게이트웨이가 path prefix를 투명하게 다룬다 (스파이크 실증, 2026-06-28)

접근 A의 본질적 미지수는 두 가지였고, 실제 코드와 게이트웨이로 **둘 다 해소**됐다(agentgateway v1.3.1).

**(1) a2a-sdk 클라이언트가 path-포함 base_url을 올바르게 다루는가 — ✅ (코드 레벨 확정)**
- `A2ACardResolver`는 카드 경로를 `base_url.rstrip('/') + '/' + agent_card_path`로 조립한다.
  `base_url="http://127.0.0.1:8080/research"` → `http://127.0.0.1:8080/research/.well-known/agent-card.json`.
- JSON-RPC transport는 카드의 `supportedInterfaces[].url`을 `self.url`로 받아 그대로 `POST self.url`을 한다.
  카드가 `http://127.0.0.1:8080/research/`를 광고하면 message/send는 정확히 그 경로로 간다.
- 즉 **오케스트레이터/SDK 코드는 변경이 전혀 필요 없다.** 카드가 광고하는 url과 오케스트레이터의 호출
  목적지 url에 prefix만 포함시키면 된다(둘 다 이미 환경변수로 외부화돼 있어 주입 값만 바뀐다).

**(2) 게이트웨이가 path prefix 매칭 + strip을 지원하는가 — ✅ (스파이크 실증)**
- 게이트웨이는 `routes[].matches[].path.pathPrefix`로 경로를 매칭하고, `policies.urlRewrite.path.prefix`로
  매칭된 prefix만 갈아끼운다(바이너리 임베드 schema의 `PathRedirect`: "Replace only the matched path prefix").
  `pathPrefix: /research` + `urlRewrite.path.prefix: /` → `/research/...`를 백엔드 `/...`로 strip한다.
- 백엔드 서버는 불변이다. 여전히 `:9001`/`:9002`의 `/`·`/.well-known/...`에서 리슨하고,
  게이트웨이가 prefix를 떼어 그 경로로 전달한다.
- 스파이크는 사용자가 띄워둔 접근 B 스택과 포트가 겹치지 않도록 **격리 포트(:18080→:19001)**로 돌렸다.
  프로덕션 config는 :8080→:9001/:9002다. 실측:
  - `curl :18080/research/.well-known/agent-card.json` → **HTTP 200**, 게이트웨이 로그
    `http.path=/research/.well-known/agent-card.json ... protocol=a2a http.status=200`
    (백엔드는 `/.well-known/...`만 아는데 200이 났으므로 strip 성공).
  - 카드 raw JSON: `supportedInterfaces[0].url == http://127.0.0.1:18080/research/` (prefix 포함 게이트웨이 url 광고).
  - a2a-sdk `A2ACardResolver(base_url=".../research")`로 파싱 → `supported_interfaces == [('http://127.0.0.1:18080/research/', 'JSONRPC')]`
    (클라이언트가 정확히 prefix 포함 url을 message/send 목적지로 읽음).
  - `POST :18080/research/` (JSON-RPC) → 게이트웨이 로그 `http.path=/research/ ... a2a.method=message/send http.status=200`,
    백엔드 JSON-RPC 레이어가 응답(요청이 백엔드까지 strip돼 도달했다는 증거).

부수 확인: 게이트웨이의 admin/stats/readiness 서버 포트(기본 15000/15020/15021)는 `config.adminAddr: "off"`
(+`statsAddr`/`readinessAddr`)로 끌 수 있다. 단 **프로덕션 config에서는 끄지 않는다** — admin/관측성은 다음 단계
(부가 정책)에서 쓸 자산이므로 기본값을 유지한다. 스파이크에서만 기존 게이트웨이와의 포트 충돌을 피하려 껐다.

### 9-B. 데이터 흐름

```
오케스트레이터(:9000)
   │  discover_agents (카드 GET) → call_agent (message/send, streaming)
   ▼
agentgateway (단일 bind :8080, policies: a2a {} + urlRewrite)
   :8080/research/*   ──[prefix /research → strip /]──▶  research 백엔드   127.0.0.1:9001
   :8080/summarizer/* ──[prefix /summarizer → strip /]─▶  summarizer 백엔드 127.0.0.1:9002
```

### 9-C. 컴포넌트별 변경

실제 코드 변경은 **config 1개 + 스크립트 1개뿐**이다. 카드(`*_PUBLIC_URL`)·레지스트리(`*_AGENT_URL`)는
접근 B에서 이미 환경변수로 외부화돼 있어, 주입하는 **값만** 단일 포트 + prefix로 바뀐다.

**(a) `config/agentgateway.yaml` — 접근 A로 교체**

2-bind를 단일 bind로 교체한다. 각 라우트는 `pathPrefix` 매칭 + `urlRewrite.path.prefix: /` strip + `a2a: {}`.

```yaml
binds:
  - port: 8080
    listeners:
      - routes:
          - matches:
              - path:
                  pathPrefix: /research
            policies:
              urlRewrite:
                path:
                  prefix: /        # /research/... → /...
              a2a: {}
            backends:
              - host: 127.0.0.1:9001
          - matches:
              - path:
                  pathPrefix: /summarizer
            policies:
              urlRewrite:
                path:
                  prefix: /
              a2a: {}
            backends:
              - host: 127.0.0.1:9002
```

**(b) `agents/*/card.py` — 변경 없음**

`*_PUBLIC_URL` 외부화는 이미 돼 있다. 게이트웨이 모드에서 주입하는 값만 prefix 포함으로 바뀐다
(`RESEARCH_PUBLIC_URL=http://127.0.0.1:8080/research/`). 미설정 시 기본값(`http://127.0.0.1:9001/`)은 하위호환용으로 유지.

**(c) `orchestrator/registry.py` — 변경 없음**

`*_AGENT_URL` 외부화는 이미 돼 있다. 주입 값만 `http://127.0.0.1:8080/research`(base_url, 끝 슬래시 X —
`A2ACardResolver`가 `rstrip('/')` 후 카드 경로를 조립하므로)로 바뀐다.

**(d) `scripts/run_with_gateway.sh` — 접근 A로 교체**

주입 env 값을 단일 포트 + prefix로 바꾼다:
- 백엔드: `RESEARCH_PUBLIC_URL=http://127.0.0.1:8080/research/`, `SUMMARIZER_PUBLIC_URL=http://127.0.0.1:8080/summarizer/`
- 오케스트레이터: `RESEARCH_AGENT_URL=http://127.0.0.1:8080/research`, `SUMMARIZER_AGENT_URL=http://127.0.0.1:8080/summarizer`
- 시작 로그 메시지도 단일 포트로 갱신.

### 9-D. 검증

스파이크로 메커니즘은 검증했으니, 프로덕션 config(:8080, 실제 키, 양 에이전트)로 §5의 검증 3종을
단일 포트 기준으로 재확인하고, 접근 A 특유의 항목을 더한다.

1. **카드 discovery + prefix url 광고** — `curl :8080/research/.well-known/agent-card.json` → 200,
   `supportedInterfaces[0].url == http://127.0.0.1:8080/research/`. summarizer도 `:8080/summarizer/...` 동일.
2. **오케스트레이터 end-to-end** — `*_AGENT_URL`을 게이트웨이 prefix로 둔 채 `POST :9000/run` →
   research→summarizer가 단일 게이트웨이 포트를 거쳐 호출되고 SSE 최종 답변 정상.
3. **스트리밍 중간 이벤트 통과(버퍼링 없음)** — 서브 에이전트 `status_update`가 prefix 라우트를 거쳐 점진 도착.
4. **path 격리** — `:8080/summarizer/...`로 research 카드가 새지 않고, 미정의 prefix(`:8080/unknown/...`)는 404로 떨어지는지.

검증은 접근 B와 동일하게 **로컬 수동 + 절차 문서화**(agentgateway는 외부 바이너리라 CI 비포함).

### 9-E. 범위 밖 (접근 B와 동일)

인증/인가·rate limit·관측성(다음 단계), TLS/CORS(로컬 PoC 불필요), 게이트웨이 바이너리 설치 자동화(수동),
게이트웨이 카드 rewrite 전환(PR #2251 포함 릴리스 나올 때 재검토 — §7-A). 모두 이번 범위 밖.
