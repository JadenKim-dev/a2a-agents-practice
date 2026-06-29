# agentgateway 기반 A2A Observability (메트릭 + 트레이싱) (PoC)

작성일: 2026-06-29
관련: [[2026-06-28-agentgateway-a2a-proxy-design]]

## 1. 목표

게이트웨이가 이미 단일 진입점(`:8080`, 접근 A)인 점을 살려, **메트릭·로그·트레이스 3종**을
게이트웨이와 Python 서비스에서 수집해 로컬 관측 스택(Prometheus + Grafana + Jaeger)으로 모은다.

이전 단계([[2026-06-28-agentgateway-a2a-proxy-design]])는 "게이트웨이가 우리 A2A 호출을 깨지 않는다"는
순수 패스스루를 증명했다. 이번 단계는 그 패스스루 위에 게이트웨이의 **부가 가치(관측성)**를 얹는다.
질문은 둘이다:

> (1) 게이트웨이가 내는 메트릭/로그를 시각화 스택으로 모아 A2A 호출량·지연·에러를 볼 수 있는가?
> (2) 오케스트레이터 → 게이트웨이 → 에이전트 경로를 **하나의 trace로** 이을 수 있는가?

### 확정된 결정 (브레인스토밍)

- **목표 깊이**: 스택까지 시각화. Prometheus(스크랩) + Grafana(대시보드) + Jaeger(트레이스)를
  docker-compose 1개로 띄운다. PoC 기조대로 게이트웨이 바이너리는 수동 설치, 관측 스택은 컨테이너.
- **트레이싱 범위**: end-to-end 연결. 게이트웨이 구간만 보는 게 아니라 오케스트레이터·에이전트
  Python 프로세스에 OpenTelemetry 계측을 더해 하나의 trace로 잇는다.
- **계측 방식**: **auto-instrumentation 중심**. 비즈니스 로직·a2a-sdk는 불변. 진입점에서 OTel SDK를
  초기화하고 httpx/FastAPI/Starlette instrumentor만 켠다. 수동 span은 넣지 않는다(YAGNI).
- **on/off**: 환경변수(`OTEL_EXPORTER_OTLP_ENDPOINT`)로 켜고 끈다. 미설정 시 no-op → 게이트웨이
  없이/관측 없이 돌리던 기존 흐름이 그대로 동작(하위호환).

## 2. 검증으로 확정한 사실 (설계 근거)

설계는 추정이 아니라 실측 위에 선다. 스파이크에서 다음을 확인했다(agentgateway v1.3.1).

### 2-A. 게이트웨이는 무설정으로 이미 관측 소스다

`config/agentgateway.yaml`에 telemetry 블록이 **전혀 없는 상태**로도 게이트웨이는:

- **Prometheus 메트릭**을 `:15020/metrics`에 낸다. `/run` 요청을 한 번 흘린 뒤 실측한 시리즈:
  - `agentgateway_requests_total{protocol="a2a",method="GET",status="503",route="default/route0",...}`
  - `agentgateway_request_duration_seconds`(히스토그램, `le` 버킷 0.001~+Inf)
  - `agentgateway_response_bytes_total`, `agentgateway_downstream_connections_total`
  - 라벨: `protocol=a2a`, `method`, `status`, `reason`, `route`(route0=research / route1=summarizer), `backend`, `bind`.
  - **메트릭은 요청 모양별로 지연 생성**된다 — 첫 요청 전에는 build/runtime 게이지만 보인다.
- **구조화 액세스 로그**를 stderr에 낸다:
  `http.method=POST http.path=/research/ ... protocol=a2a a2a.method=SendStreamingMessage http.status=200 duration=7019ms`
  (이전 단계 §9-E에서 이미 실측).

→ 메트릭·로그는 **손대지 않아도** 나온다. 우리가 할 일은 (a) 스크랩 타깃으로 묶고 (b) 대시보드를 그리는 것뿐.

### 2-B. 게이트웨이는 W3C traceparent를 채택하고 OTLP로 송출할 수 있다

- `config.tracing.otlpEndpoint`(+`randomSampling`)를 추가한 config가 v1.3.1 `--validate-only`를 통과한다
  ("Configuration is valid!").
- 게이트웨이에 `traceparent: 00-0af7651916cd43dd8448eb211c80319c-...`를 실어 보낸 요청의 로그가
  `trace.id=0af7651916cd43dd8448eb211c80319c span.id=3f685e7068fdfb46`로 찍혔다 —
  **수신한 traceparent의 trace-id를 그대로 채택**하고 자식 span을 만든다. 즉 게이트웨이는 W3C trace
  context에 참여한다.

### 2-C. Python 쪽은 auto-instrumentation만으로 trace가 이어진다 (코드 불변)

- **클라이언트(오케스트레이터)**: a2a-sdk JSONRPC transport는 공유 `httpx_client`로
  `build_request` → `send`를 한다(`a2a/client/transports/jsonrpc.py:346-349`,
  `http_helpers.py:67`). 전송 경로에 **헤더 화이트리스트/스트리핑이 없다.** 따라서
  `HTTPXClientInstrumentor`가 `send`를 후킹해 `traceparent`를 주입하면, a2a-sdk 코드 변경 없이
  헤더가 그대로 게이트웨이로 나간다. (오케스트레이터는 `ClientFactory(ClientConfig(httpx_client=...))`로
  client 하나를 공유하므로 — `orchestrator/client.py:17` — 전역 httpx 계측이 곧바로 적용된다.)
- **서버(에이전트·오케스트레이터)**: 에이전트는 Starlette(`common/server.py`의 `build_starlette_app`),
  오케스트레이터는 FastAPI(`orchestrator/server.py`의 `build_app`). 둘 다 표준 ASGI라
  `StarletteInstrumentor`/`FastAPIInstrumentor`가 수신 요청의 `traceparent`를 읽어 span을 이어받는다.

## 3. 관측 스택 아키텍처

```
┌─ orchestrator(:9000, FastAPI) ──┐   httpx(traceparent 주입)
│                                  ▼
│                         agentgateway(:8080, a2a + tracing)
│   metrics :15020/metrics ──┐         │ /research/*   → :9001
│   traces  OTLP :4317 ──────┤         │ /summarizer/* → :9002
└────────────────────────────┤         ▼
   research/summarizer(Starlette, traceparent 수신)
                              │
          ┌───────────────────┴────────────────────┐
          ▼                                         ▼
   Prometheus(scrape :15020) ──▶ Grafana       Jaeger(OTLP 수집/조회)
        (대시보드)                              (:4317 수신 / :16686 UI)
```

- 메트릭: Prometheus가 호스트의 게이트웨이 `:15020/metrics`를 스크랩 → Grafana 대시보드.
- 트레이스: 오케스트레이터·게이트웨이·에이전트가 각자 OTLP로 Jaeger(`:4317`)에 span을 보냄 →
  Jaeger UI(`:16686`)에서 trace-id로 한데 묶여 조회됨.
- 관측 스택(Prometheus/Grafana/Jaeger)은 **docker-compose 1개 파일**. 게이트웨이 바이너리만 수동.

## 4. 컴포넌트별 변경

핵심 원칙: 게이트웨이 config는 telemetry 블록만 더하고, Python은 부트스트랩 파일 하나로
auto-instrumentation을 켠다(비즈니스 로직·a2a-sdk 불변). 관측은 환경변수로 on/off.

### (a) `config/agentgateway.yaml` — `config.tracing` 추가

기존 라우트(접근 A 단일 포트 + path-prefix)는 그대로 두고 `config.tracing`만 더한다.

```yaml
config:
  tracing:
    otlpEndpoint: http://localhost:4317   # Jaeger OTLP gRPC
    randomSampling: true                  # PoC는 100% 샘플링
binds:
  - port: 8080
    listeners:
      - routes:
          # ... (기존 /research, /summarizer 라우트 그대로)
```

메트릭(`:15020`)·액세스 로그는 무설정으로 이미 나오므로 손대지 않는다. v1.3.1 `--validate-only` 통과 확인 완료.

### (b) `common/telemetry.py` (신규) — OTel 부트스트랩 한 곳

세 프로세스가 공유하는 초기화 함수 하나. `OTEL_EXPORTER_OTLP_ENDPOINT`가 설정돼 있을 때만 동작
(없으면 즉시 return → no-op → 하위호환).

```python
def setup_telemetry(service_name: str) -> None:
    """OTLP 엔드포인트가 설정돼 있으면 OTel tracer와 httpx 전역 계측을 켠다.

    엔드포인트 미설정 시 아무것도 하지 않는다(관측 off).
    """
    # endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    # if not endpoint: return
    # TracerProvider(resource=service.name) + OTLPSpanExporter(endpoint) + BatchSpanProcessor
    # HTTPXClientInstrumentor().instrument()   # 전역 → 공유 httpx client에 traceparent 주입
```

- **httpx 계측은 전역**이라 오케스트레이터의 공유 client에 자동 적용 — 2-C대로 a2a-sdk 불변으로 traceparent가 나간다.
- ASGI 계측은 앱 인스턴스에 걸어야 하므로 (c)에서 앱 빌더/진입점이 호출한다. `setup_telemetry`는
  TracerProvider 등록과 httpx 계측까지 담당하고, ASGI instrumentor는 앱이 만들어지는 곳에서 건다.

### (c) 진입점 3곳 — `setup_telemetry()` 호출 + ASGI 앱 계측

- `orchestrator/__main__.py`: `setup_telemetry("orchestrator")` 호출 후 `build_app()` 결과에
  `FastAPIInstrumentor.instrument_app(app)`.
- `agents/research/__main__.py`, `agents/summarizer/__main__.py`: `setup_telemetry("research"/"summarizer")`
  호출 후 Starlette 앱에 `StarletteInstrumentor`.
- 에이전트는 현재 `run_agent_server(card, executor, host, port)`가 앱 생성과 uvicorn 기동을 함께 한다
  (`common/server.py`). ASGI 계측을 깔끔히 걸려면 **`build_starlette_app`로 앱을 먼저 만들고
  계측을 건 뒤 uvicorn에 넘기는** 형태가 자연스럽다. 빌더 시그니처는 그대로 두고, 진입점에서
  `app = build_starlette_app(card, executor)` → `StarletteInstrumentor().instrument_app(app)` →
  `uvicorn.run(app, ...)` 순으로 조립한다. (계측 훅을 `run_agent_server` 내부에 숨기지 않고
  진입점에 노출해, "관측을 켜는 주체는 진입점"이라는 경계를 분명히 한다.)

### (d) `docker-compose.observability.yml` (신규) + 프로비저닝

관측 스택을 컨테이너로 띄운다. 게이트웨이/Python은 호스트에서 돈다(기존 스크립트 그대로).

- **Prometheus**: `:15020/metrics`를 스크랩하는 `scrape_configs` 1개. macOS 컨테이너에서 호스트의
  게이트웨이를 가리키므로 타깃은 `host.docker.internal:15020`.
- **Grafana**: Prometheus 데이터소스 + **A2A 대시보드 1개**를 provisioning으로 자동 등록. 패널:
  호출량(`rate(agentgateway_requests_total[1m])`), p50/p95 지연(`request_duration_seconds` 히스토그램),
  에러율(`status` 라벨 4xx/5xx 비율), 에이전트별 분기(`route` 라벨 route0/route1).
- **Jaeger**: all-in-one. OTLP gRPC `:4317` 수신 + UI `:16686`. (별도 OTel Collector를 두지 않는다 —
  Jaeger가 OTLP를 직접 받으므로 불필요, YAGNI.)
- 프로비저닝 파일: `config/observability/prometheus.yml`, `config/observability/grafana/`(datasource +
  dashboard JSON).

### (e) `pyproject.toml` — OTel 의존성을 `observability` extra로

기본 설치엔 영향이 없도록 선택적 extra로 묶는다(`pip install -e ".[observability]"`).

```toml
[project.optional-dependencies]
observability = [
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp>=1.27",
    "opentelemetry-instrumentation-httpx>=0.48b0",
    "opentelemetry-instrumentation-fastapi>=0.48b0",
    "opentelemetry-instrumentation-starlette>=0.48b0",
]
```

(버전은 구현 시 현재 venv(Python 3.14)와 호환되는 최신으로 확정한다.)

### (f) `scripts/run_with_gateway.sh` — 관측 env 주입 (선택적)

게이트웨이 모드 스크립트에 `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`을 세 프로세스에
주입하는 경로를 더한다. 단, 미설정 시 no-op이므로 **관측을 끄고 돌리는 기존 경로도 유지**한다
(env를 주입하지 않으면 그대로 패스스루). README에 "관측 스택을 먼저 docker-compose로 띄운 뒤
스크립트를 OTEL env와 함께 실행" 절차를 적는다.

## 5. 트레이스 전파 흐름과 끊김 지점

end-to-end span이 어떻게 이어지는지, 어디가 약한지 명시한다.

```
POST :9000/run
  └─ [span] orchestrator FastAPI (root)                 ← FastAPIInstrumentor 생성
       └─ httpx POST :8080/research/  (traceparent 주입)  ← HTTPXClientInstrumentor (2-C)
            └─ [span] gateway /research/                  ← traceparent 채택(2-B 실측), OTLP 송출
                 └─ [span] research Starlette             ← StarletteInstrumentor가 수신 헤더로 이어받음
       └─ httpx POST :8080/summarizer/ (traceparent 주입)
            └─ [span] gateway /summarizer/
                 └─ [span] summarizer Starlette
```

**확정된 연결 고리** (2장 실측): 클라이언트 주입(2-C), 게이트웨이 채택(2-B), 서버 수신(2-C).

**남는 약점 (정직하게 명시):**

- **에이전트 내부 LangGraph/LLM 호출**은 노드 단위 계측 밖이다. research가 부르는 Tavily/OpenAI는
  전역 httpx 계측에 잡혀 span이 생기지만, LangGraph 노드별 span은 없다. PoC엔 충분.
- **SSE 스트리밍 span**: 게이트웨이가 수 초~십수 초짜리 `SendStreamingMessage`를 하나의 긴 span으로
  잡는다. 중간 진행 이벤트는 trace가 아니라 메트릭/로그로 본다 — 이게 의도된 그림.
- **트레이스 연결의 본질적 미지수**: 2-C는 코드 레벨/스파이크로 강하게 뒷받침되지만, "오케스트레이터
  root span → 게이트웨이 → 에이전트"가 **실제로 한 trace-id로 Jaeger에 묶이는지**는 전체 스택을
  띄워 확인해야 최종 확정된다(§6 검증 3번). 만약 어느 홉에서 끊기면 게이트웨이 구간 span만 보이는
  부분 trace로 떨어지며, 그 경우에도 메트릭/대시보드(§4-d)는 온전히 동작한다.

## 6. 검증

기존 단계와 동일하게 **로컬 수동 + 절차 문서화**. agentgateway는 외부 바이너리라 CI 비포함.

1. **메트릭 노출·스크랩**: 관측 스택을 띄우고 `/run` 1회 후
   `curl :15020/metrics`에 `agentgateway_requests_total{protocol="a2a",route="default/route0",status="200"}`
   등 A2A 시리즈가 등장하고, Prometheus 타깃이 `UP`, Grafana 패널에 값이 그려지는지.
2. **대시보드**: 호출량·p95 지연·에러율·에이전트별(route0/route1) 분기 패널이 정상 렌더되는지.
3. **end-to-end 트레이스**: Jaeger UI에서 한 `/run`이
   `orchestrator → gateway(/research) → research → gateway(/summarizer) → summarizer` span으로
   **한 trace에 묶이는지**(traceparent 연결 최종 확인 — §5의 미지수 해소 지점).
4. **하위호환**: `OTEL_*`·`config.tracing` 미설정으로 띄우면 기존 패스스루가 그대로 동작하고
   관측이 no-op으로 꺼지는지(게이트웨이 없는 직접 실행 경로 포함).

## 7. 범위 밖 (YAGNI)

- **인증/인가·rate limit** — 관측과 독립한 다음 단계.
- **LangGraph 노드별 trace, LLM 토큰/비용 메트릭** — auto-instrumentation 밖, PoC 과함.
- **메트릭/트레이스 영구 저장·알림(Alertmanager)** — 로컬 PoC 불필요, 컨테이너 재시작 시 휘발 허용.
- **수동 span/속성 추가** — auto-instrumentation으로 충분, 비즈니스 코드에 계측 코드 안 섞음.
- **OTel Collector 별도 띄우기** — Jaeger all-in-one이 OTLP를 직접 수신하므로 생략.
- **TLS/프로덕션 배포 매니페스트(k8s 등)** — 로컬 docker-compose로 충분.
- **게이트웨이 카드 rewrite 전환** — 이전 단계의 별개 추적 항목(이전 spec §7-A), 이번 범위 밖.
