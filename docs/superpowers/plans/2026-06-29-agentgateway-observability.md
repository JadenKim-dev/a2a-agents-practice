# agentgateway 기반 A2A Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** agentgateway 단일 진입점(`:8080`) 위에 메트릭·트레이스를 얹어, Prometheus + Grafana + Jaeger로 A2A 호출량·지연·에러와 오케스트레이터→게이트웨이→에이전트 end-to-end trace를 본다.

**Architecture:** 게이트웨이는 무설정으로 이미 `:15020/metrics`(Prometheus)와 구조화 로그를 낸다 — 여기에 `config.tracing`만 더해 OTLP trace를 켠다. Python 3개 프로세스(오케스트레이터·research·summarizer)는 진입점에서 OTel auto-instrumentation(httpx/FastAPI/Starlette)만 켜 비즈니스 로직·a2a-sdk 불변으로 traceparent를 전파·수신한다. 관측 스택은 docker-compose 1개로 띄우고, 모든 계측은 환경변수로 on/off(미설정 시 no-op → 하위호환).

**Tech Stack:** agentgateway v1.3.1, OpenTelemetry Python SDK(1.43.0) + OTLP gRPC exporter + httpx/fastapi/starlette instrumentation(0.64b0), Prometheus, Grafana, Jaeger all-in-one, docker-compose, pytest.

## Global Constraints

- **agentgateway 버전**: v1.3.1 (이미 설치됨, `~/.local/bin/agentgateway`). config는 `--validate-only`로 스키마 통과 확인할 것.
- **관측은 환경변수로 on/off**: `OTEL_EXPORTER_OTLP_ENDPOINT` 미설정 시 모든 OTel 계측은 no-op. 게이트웨이 `config.tracing` 미설정/관측 스택 미기동 시에도 기존 패스스루는 그대로 동작해야 한다(하위호환).
- **비즈니스 로직·a2a-sdk 불변**: 계측은 진입점(`__main__.py`)과 `common/telemetry.py`에만. `orchestrator/orchestrate.py`·`client.py`·`agents/*/graph.py` 등 비즈니스 코드에 계측 코드를 섞지 않는다(수동 span 금지, YAGNI).
- **OTel 의존성은 선택적 extra**: `pyproject.toml`의 `[project.optional-dependencies] observability`로 분리. 기본 설치(`pip install -e .`)엔 영향 없음.
- **Python 3.14** (venv `.venv/bin/python`). 검증된 설치 버전: `opentelemetry-sdk==1.43.0`, exporter `opentelemetry-exporter-otlp-proto-grpc==1.43.0`, instrumentation `*==0.64b0`.
- **테스트 규칙**(사용자 CLAUDE.md): 각 케이스에 `# given`/`# when`/`# then` 주석. 입력은 `it`/test 함수 안에 리터럴로. 환경변수 의존 모듈은 `monkeypatch` + `importlib.reload` 패턴(기존 `tests/test_card_public_url.py` 참고). 관측 가능한 동작으로 케이스 이름 짓기.
- **docstring**: 한글 명사구/declarative("~한다") (사용자 선호, 기존 코드 일관).
- **테스트는 네트워크 없이**: OTLP exporter는 실제 송출 대신 in-memory exporter로 검증. agentgateway/docker는 CI 비포함 — 수동 검증 + 절차 문서화.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `common/telemetry.py` | OTLP 엔드포인트가 있으면 TracerProvider 등록 + httpx 전역 계측을 켠다 | Create |
| `pyproject.toml` | `observability` extra로 OTel 의존성 분리 | Modify |
| `config/agentgateway.yaml` | 기존 라우트 위에 `config.tracing` 추가 | Modify |
| `orchestrator/__main__.py` | `setup_telemetry("orchestrator")` + FastAPI 앱 계측 | Modify |
| `agents/research/__main__.py` | `setup_telemetry("research")` + Starlette 앱 계측 | Modify |
| `agents/summarizer/__main__.py` | `setup_telemetry("summarizer")` + Starlette 앱 계측 | Modify |
| `orchestrator/server.py` | (변경 없음 — 앱 계측은 진입점에서) | — |
| `config/observability/prometheus.yml` | 게이트웨이 `:15020`를 스크랩하는 Prometheus 설정 | Create |
| `config/observability/grafana/datasource.yml` | Grafana Prometheus 데이터소스 프로비저닝 | Create |
| `config/observability/grafana/dashboards.yml` | Grafana 대시보드 provider 프로비저닝 | Create |
| `config/observability/grafana/a2a-dashboard.json` | A2A 호출량·지연·에러·에이전트별 대시보드 | Create |
| `docker-compose.observability.yml` | Prometheus + Grafana + Jaeger 스택 | Create |
| `scripts/run_with_gateway.sh` | OTEL env 주입 경로 추가 | Modify |
| `README.md` | 관측 스택 기동·검증 절차 | Modify |
| `tests/test_telemetry.py` | `setup_telemetry` no-op/on 동작 검증 | Create |

**Task 의존성**: Task 1(telemetry 모듈) → Task 2(extra 의존성) → Task 3(진입점 계측) 은 Python trace 경로. Task 4(게이트웨이 tracing config) + Task 5(관측 스택 compose/provisioning) 은 인프라. Task 6(스크립트/README) 은 묶기. Task 7 은 수동 검증. Task 1~5는 Task 1 이후 서로 독립적이나, 검증(Task 7)은 전부 필요.

---

### Task 1: `common/telemetry.py` — OTel 부트스트랩

**Files:**
- Create: `common/telemetry.py`
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: 환경변수 `OTEL_EXPORTER_OTLP_ENDPOINT`(예: `http://localhost:4317`), `OTEL_SERVICE_NAME`(선택, 인자로도 받음).
- Produces:
  - `setup_telemetry(service_name: str) -> bool` — OTLP 엔드포인트가 설정돼 있으면 TracerProvider를 전역 등록하고 `HTTPXClientInstrumentor`를 켠 뒤 `True`를 반환한다. 미설정 시 아무것도 하지 않고 `False`를 반환한다(no-op). Task 3의 진입점들이 이 함수를 호출한다.

- [ ] **Step 1: Write the failing test**

`tests/test_telemetry.py`:

```python
"""OTLP 엔드포인트 유무에 따른 setup_telemetry on/off 동작을 검증한다."""
import importlib

import common.telemetry as telemetry


def test_returns_false_and_no_op_when_endpoint_unset(monkeypatch):
    # given
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    module = importlib.reload(telemetry)

    # when
    enabled = module.setup_telemetry("orchestrator")

    # then
    assert enabled is False


def test_returns_true_and_registers_provider_when_endpoint_set(monkeypatch):
    # given
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    module = importlib.reload(telemetry)

    # when
    enabled = module.setup_telemetry("research")

    # then
    from opentelemetry import trace
    assert enabled is True
    assert trace.get_tracer_provider().__class__.__name__ == "TracerProvider"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.telemetry'` (또는 `opentelemetry` 미설치 시 import 에러 → Task 2를 먼저 설치하거나, 이 Task의 Step 3 직후 Task 2 Step 1을 실행해도 됨. 권장: Task 2의 `pip install`을 먼저 수행).

> 참고: OTel 패키지가 아직 없으면 이 테스트의 `from opentelemetry import trace`가 collection 단계에서 실패한다. 이 Task를 시작하기 전에 Task 2 Step 1(설치)을 먼저 끝내는 것을 권장한다. 두 Task는 함께 묶어 진행해도 좋다.

- [ ] **Step 3: Write minimal implementation**

`common/telemetry.py`:

```python
"""OTLP 엔드포인트가 설정돼 있으면 OTel tracer와 httpx 전역 계측을 켠다."""
import os


def setup_telemetry(service_name: str) -> bool:
    """OTLP 엔드포인트가 있으면 TracerProvider 등록과 httpx 계측을 켜고 True를, 없으면 no-op으로 False를 반환한다."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return True
```

> 설계 메모: import를 함수 안에 둔 이유 — OTel 미설치(기본 설치) 환경에서도 `setup_telemetry`를 import하고 endpoint 미설정 경로(no-op)를 타는 데 OTel 패키지가 필요 없게 하기 위함. 하위호환(Global Constraints)의 핵심.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_telemetry.py -v`
Expected: PASS (2 passed). OTLP exporter는 `BatchSpanProcessor`가 백그라운드로 송출 시도만 하므로 Jaeger 미기동이어도 테스트는 통과한다(연결 실패는 비동기로 무시됨).

- [ ] **Step 5: Commit**

```bash
git add common/telemetry.py tests/test_telemetry.py
git commit -m "feat: OTLP 엔드포인트가 있을 때만 OTel tracer/httpx 계측을 켜는 telemetry 부트스트랩 추가"
```

---

### Task 2: `pyproject.toml` — `observability` extra

**Files:**
- Modify: `pyproject.toml:18-23` (`[project.optional-dependencies]` 블록)

**Interfaces:**
- Consumes: 없음.
- Produces: `pip install -e ".[observability]"`로 설치되는 OTel 의존성 집합. Task 1·3이 import하는 `opentelemetry.*` 패키지를 제공.

- [ ] **Step 1: 의존성 추가**

`pyproject.toml`의 `[project.optional-dependencies]`에 `observability` 항목을 추가한다(기존 `dev`는 그대로):

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "anyio>=4",
]
observability = [
    "opentelemetry-sdk>=1.43,<2",
    "opentelemetry-exporter-otlp-proto-grpc>=1.43,<2",
    "opentelemetry-instrumentation-httpx>=0.64b0,<1",
    "opentelemetry-instrumentation-fastapi>=0.64b0,<1",
    "opentelemetry-instrumentation-starlette>=0.64b0,<1",
]
```

- [ ] **Step 2: 설치 후 import 가능 확인**

Run:
```bash
.venv/bin/python -m pip install -e ".[observability]" && \
.venv/bin/python -c "from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter; \
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor; \
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor; \
from opentelemetry.instrumentation.starlette import StarletteInstrumentor; \
print('otel imports ok')"
```
Expected: 마지막 줄에 `otel imports ok`. (Python 3.14에서 `opentelemetry-sdk 1.43.0`, instrumentation `0.64b0`이 해석/설치됨 — dry-run으로 확인된 조합.)

- [ ] **Step 3: 기본 설치는 OTel 없이도 telemetry import가 되는지 (하위호환) 확인**

Run:
```bash
OTEL_EXPORTER_OTLP_ENDPOINT= .venv/bin/python -c "from common.telemetry import setup_telemetry; print(setup_telemetry('x'))"
```
Expected: `False` (endpoint 미설정 → no-op, OTel import 경로를 타지 않음).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: OTel 계측 의존성을 observability extra로 분리"
```

---

### Task 3: 진입점 3곳 — `setup_telemetry()` 호출 + ASGI 앱 계측

**Files:**
- Modify: `orchestrator/__main__.py`
- Modify: `agents/research/__main__.py`
- Modify: `agents/summarizer/__main__.py`

**Interfaces:**
- Consumes: `common.telemetry.setup_telemetry(service_name)` (Task 1), `common.server.build_starlette_app(card, executor)` (기존), `orchestrator.server.build_app()` (기존).
- Produces: 관측 활성 시 각 프로세스가 OTel span을 생성·전파하는 실행 진입점. 외부에 새 심볼을 노출하지 않음(진입점 내부 조립 변경).

- [ ] **Step 1: 오케스트레이터 진입점에 계측 추가**

`orchestrator/__main__.py`를 다음으로 교체한다:

```python
"""오케스트레이터 서버 진입점: python -m orchestrator → :9000 SSE 서버."""
import uvicorn
from dotenv import load_dotenv

from common.telemetry import setup_telemetry
from orchestrator.server import build_app

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("orchestrator")
    app = build_app()
    if enabled:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: research 진입점에 계측 추가**

`agents/research/__main__.py`를 다음으로 교체한다(앱을 먼저 만들고 계측 후 uvicorn에 넘기는 형태):

```python
"""Research 에이전트 서버 진입점: python -m agents.research → :9001."""
import uvicorn
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import build_starlette_app
from common.telemetry import setup_telemetry
from agents.research.card import RESEARCH_CARD
from agents.research.graph import build_research_graph

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("research")
    executor = LangGraphExecutor(build_research_graph())
    app = build_starlette_app(RESEARCH_CARD, executor)
    if enabled:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
        StarletteInstrumentor().instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9001)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: summarizer 진입점에 계측 추가**

`agents/summarizer/__main__.py`를 다음으로 교체한다:

```python
"""Summarizer 에이전트 서버 진입점: python -m agents.summarizer → :9002."""
import uvicorn
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import build_starlette_app
from common.telemetry import setup_telemetry
from agents.summarizer.card import SUMMARIZER_CARD
from agents.summarizer.graph import build_summarizer_graph

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("summarizer")
    executor = LangGraphExecutor(build_summarizer_graph())
    app = build_starlette_app(SUMMARIZER_CARD, executor)
    if enabled:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
        StarletteInstrumentor().instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9002)


if __name__ == "__main__":
    main()
```

> 참고: 기존 `common.server.run_agent_server`는 더 이상 진입점에서 쓰지 않는다(앱 생성과 계측을 분리하기 위해 `build_starlette_app` + `uvicorn.run`을 진입점에서 직접 조립). `run_agent_server`는 그대로 남겨둔다(다른 호출부·테스트가 없으면 제거 대신 보존 — 별도 정리는 범위 밖).

- [ ] **Step 4: 기존 테스트가 깨지지 않는지 확인**

Run: `.venv/bin/python -m pytest tests/test_server.py tests/test_telemetry.py -v`
Expected: PASS. (`build_starlette_app`는 시그니처 불변이라 `test_server.py`는 영향 없음. 진입점은 `if __name__`로 감싸 import만으로는 실행되지 않음.)

- [ ] **Step 5: 관측 OFF로 진입점 import가 되는지(하위호환) 확인**

Run:
```bash
OTEL_EXPORTER_OTLP_ENDPOINT= .venv/bin/python -c "import orchestrator.__main__, agents.research.__main__, agents.summarizer.__main__; print('entrypoints import ok')"
```
Expected: `entrypoints import ok` (계측 import는 `if enabled:` 안이라 OTel 미설정 시 타지 않음).

- [ ] **Step 6: Commit**

```bash
git add orchestrator/__main__.py agents/research/__main__.py agents/summarizer/__main__.py
git commit -m "feat: 진입점에서 관측 활성 시 FastAPI/Starlette 앱을 OTel 계측"
```

---

### Task 4: `config/agentgateway.yaml` — `config.tracing` 추가

**Files:**
- Modify: `config/agentgateway.yaml:4` (`binds:` 위에 `config:` 블록 추가)

**Interfaces:**
- Consumes: Jaeger OTLP gRPC 엔드포인트 `http://localhost:4317` (Task 5가 띄움).
- Produces: 게이트웨이가 trace를 OTLP로 Jaeger에 송출. 메트릭(`:15020`)·기존 라우트는 불변.

- [ ] **Step 1: tracing 블록 추가**

`config/agentgateway.yaml` 최상단(주석 다음, `binds:` 앞)에 `config:` 블록을 추가한다. 기존 `binds` 이하는 그대로 둔다:

```yaml
# research/summarizer A2A 서버 앞단에 두는 단일 포트 + path-prefix 프록시 설정(접근 A).
# :8080/research/*   → :9001 (research),   prefix /research 를 strip 후 백엔드 / 로 전달.
# :8080/summarizer/* → :9002 (summarizer), prefix /summarizer 를 strip 후 백엔드 / 로 전달.
config:
  # 게이트웨이 구간 trace를 Jaeger(OTLP gRPC :4317)로 송출한다. 수신한 W3C traceparent를 채택해 자식 span을 만든다.
  tracing:
    otlpEndpoint: http://localhost:4317
    randomSampling: true
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
                  prefix: /
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

- [ ] **Step 2: config 스키마 검증**

Run: `agentgateway -f config/agentgateway.yaml --validate-only`
Expected: `Configuration is valid!` (exit 0). v1.3.1 스키마에서 `config.tracing.otlpEndpoint`/`randomSampling`이 통과함은 사전 확인됨.

- [ ] **Step 3: Commit**

```bash
git add config/agentgateway.yaml
git commit -m "feat: 게이트웨이 config.tracing 추가 — 게이트웨이 구간 trace를 Jaeger OTLP로 송출"
```

---

### Task 5: 관측 스택 — docker-compose + Prometheus/Grafana 프로비저닝

**Files:**
- Create: `config/observability/prometheus.yml`
- Create: `config/observability/grafana/datasource.yml`
- Create: `config/observability/grafana/dashboards.yml`
- Create: `config/observability/grafana/a2a-dashboard.json`
- Create: `docker-compose.observability.yml`

**Interfaces:**
- Consumes: 호스트의 게이트웨이 메트릭 `:15020/metrics`, 게이트웨이/Python의 OTLP trace.
- Produces: Prometheus(`:9090`), Grafana(`:3000`, A2A 대시보드), Jaeger UI(`:16686`) + OTLP 수신(`:4317`).

- [ ] **Step 1: Prometheus 스크랩 설정**

`config/observability/prometheus.yml`:

```yaml
# agentgateway가 :15020/metrics에 내는 A2A 메트릭을 스크랩한다.
# 게이트웨이는 호스트에서 돌므로 컨테이너에서 host.docker.internal로 가리킨다(macOS/Windows Docker Desktop).
global:
  scrape_interval: 5s
scrape_configs:
  - job_name: agentgateway
    static_configs:
      - targets: ["host.docker.internal:15020"]
```

- [ ] **Step 2: Grafana 데이터소스 프로비저닝**

`config/observability/grafana/datasource.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

- [ ] **Step 3: Grafana 대시보드 provider 프로비저닝**

`config/observability/grafana/dashboards.yml`:

```yaml
apiVersion: 1
providers:
  - name: a2a
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

- [ ] **Step 4: A2A 대시보드 JSON**

`config/observability/grafana/a2a-dashboard.json` — 호출량·p95 지연·에러율·에이전트별(route) 4패널:

```json
{
  "title": "A2A via agentgateway",
  "uid": "a2a-gateway",
  "schemaVersion": 39,
  "time": { "from": "now-15m", "to": "now" },
  "panels": [
    {
      "title": "A2A 호출량 (req/s, route별)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "targets": [
        { "expr": "sum by (route) (rate(agentgateway_requests_total{protocol=\"a2a\"}[1m]))", "legendFormat": "{{route}}" }
      ]
    },
    {
      "title": "지연 p95 (s, route별)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "targets": [
        { "expr": "histogram_quantile(0.95, sum by (le, route) (rate(agentgateway_request_duration_seconds_bucket{protocol=\"a2a\"}[5m])))", "legendFormat": "{{route}}" }
      ]
    },
    {
      "title": "에러율 (5xx 비율)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "targets": [
        { "expr": "sum(rate(agentgateway_requests_total{protocol=\"a2a\",status=~\"5..\"}[1m])) / sum(rate(agentgateway_requests_total{protocol=\"a2a\"}[1m]))", "legendFormat": "5xx ratio" }
      ]
    },
    {
      "title": "상태코드별 호출 (route×status)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "targets": [
        { "expr": "sum by (route, status) (rate(agentgateway_requests_total{protocol=\"a2a\"}[1m]))", "legendFormat": "{{route}} {{status}}" }
      ]
    }
  ]
}
```

- [ ] **Step 5: docker-compose 스택**

`docker-compose.observability.yml`:

```yaml
# 로컬 관측 스택: Prometheus(메트릭 스크랩) + Grafana(대시보드) + Jaeger(트레이스).
# 게이트웨이/Python은 호스트에서 돈다. 컨테이너에서 호스트로는 host.docker.internal로 접근.
services:
  prometheus:
    image: prom/prometheus:v2.55.1
    ports:
      - "9090:9090"
    volumes:
      - ./config/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"

  grafana:
    image: grafana/grafana:11.4.0
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
      - GF_AUTH_DISABLE_LOGIN_FORM=true
    volumes:
      - ./config/observability/grafana/datasource.yml:/etc/grafana/provisioning/datasources/datasource.yml:ro
      - ./config/observability/grafana/dashboards.yml:/etc/grafana/provisioning/dashboards/dashboards.yml:ro
      - ./config/observability/grafana/a2a-dashboard.json:/etc/grafana/provisioning/dashboards/a2a-dashboard.json:ro

  jaeger:
    image: jaegertracing/all-in-one:1.62.0
    ports:
      - "16686:16686"   # UI
      - "4317:4317"     # OTLP gRPC
    environment:
      - COLLECTOR_OTLP_ENABLED=true
```

- [ ] **Step 6: 스택 기동 + 헬스 확인**

Run:
```bash
docker compose -f docker-compose.observability.yml up -d && sleep 8 && \
curl -s -o /dev/null -w "prom %{http_code}\n" http://localhost:9090/-/ready && \
curl -s -o /dev/null -w "grafana %{http_code}\n" http://localhost:3000/api/health && \
curl -s -o /dev/null -w "jaeger %{http_code}\n" http://localhost:16686/
```
Expected: `prom 200`, `grafana 200`, `jaeger 200`. (Docker Desktop 필요 — 없으면 README에 안내하고 이 Step은 환경 준비 후 수행.)

- [ ] **Step 7: Commit**

```bash
git add config/observability/ docker-compose.observability.yml
git commit -m "feat: 관측 스택(Prometheus+Grafana+Jaeger) docker-compose와 A2A 대시보드 추가"
```

---

### Task 6: 스크립트 + README — 관측 모드 절차

**Files:**
- Modify: `scripts/run_with_gateway.sh:16-30`
- Modify: `README.md` (게이트웨이 섹션 뒤에 관측 절차 추가)

**Interfaces:**
- Consumes: Task 1~5의 산출물.
- Produces: `OBSERVABILITY=1` 환경에서 OTEL env를 세 프로세스에 주입하는 기동 경로 + 검증 절차 문서.

- [ ] **Step 1: 스크립트에 OTEL env 주입 경로 추가**

`scripts/run_with_gateway.sh`에서, 관측이 켜졌을 때만 세 프로세스에 `OTEL_EXPORTER_OTLP_ENDPOINT`를 주입한다. 기존 백엔드/오케스트레이터 기동부를 다음으로 바꾼다(환경변수 가드로 하위호환 유지):

```bash
# 관측 모드: OBSERVABILITY=1 이면 OTEL 엔드포인트를 주입해 trace를 켠다(미설정 시 no-op).
OTEL_ENV=""
if [ "${OBSERVABILITY:-0}" = "1" ]; then
  OTEL_ENV="OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317"
  echo "observability ON → OTLP traces to http://localhost:4317 (Jaeger)"
fi

env $OTEL_ENV RESEARCH_PUBLIC_URL="http://127.0.0.1:8080/research/" python -m agents.research &
RESEARCH_PID=$!
env $OTEL_ENV SUMMARIZER_PUBLIC_URL="http://127.0.0.1:8080/summarizer/" python -m agents.summarizer &
SUMMARIZER_PID=$!

agentgateway -f config/agentgateway.yaml &
GATEWAY_PID=$!

# 백엔드와 게이트웨이가 리슨할 시간을 준 뒤 오케스트레이터를 띄운다.
sleep 2

env $OTEL_ENV \
  RESEARCH_AGENT_URL="http://127.0.0.1:8080/research" \
  SUMMARIZER_AGENT_URL="http://127.0.0.1:8080/summarizer" \
  python -m orchestrator &
ORCHESTRATOR_PID=$!
```

(파일 상단의 `set -euo pipefail`, `cd`, agentgateway 존재 체크, `cleanup`/`trap`, 마지막 `echo`/`wait`는 그대로 둔다.)

- [ ] **Step 2: 스크립트 문법 확인**

Run: `bash -n scripts/run_with_gateway.sh && echo "syntax ok"`
Expected: `syntax ok`.

- [ ] **Step 3: README에 관측 절차 추가**

`README.md`의 "(선택) agentgateway 프록시 모드" 섹션 끝에 다음을 추가한다:

```markdown
### (선택) Observability — 메트릭 + 트레이싱

게이트웨이는 무설정으로 `:15020/metrics`에 Prometheus 메트릭과 구조화 로그를 낸다.
여기에 trace까지 더해 로컬 관측 스택(Prometheus + Grafana + Jaeger)으로 본다.

```bash
# 1) 관측 스택 기동 (Docker Desktop 필요)
docker compose -f docker-compose.observability.yml up -d
#    Prometheus :9090, Grafana :3000, Jaeger UI :16686

# 2) OTel 계측 의존성 설치
pip install -e ".[observability]"

# 3) 관측 ON으로 전체 스택 기동
OBSERVABILITY=1 ./scripts/run_with_gateway.sh

# 4) 트래픽 발생
curl -N -X POST http://127.0.0.1:9000/run \
  -H 'content-type: application/json' \
  -d '{"task":"양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"}'
```

- **메트릭/대시보드**: Grafana(http://localhost:3000) → "A2A via agentgateway" 대시보드에서
  호출량·p95 지연·에러율·에이전트별(route0=research/route1=summarizer) 분기를 본다.
- **트레이스**: Jaeger UI(http://localhost:16686) → service `orchestrator`에서 한 `/run`을 고르면
  `orchestrator → gateway → research → gateway → summarizer` span이 한 trace로 묶여 보인다.
- 관측을 끄려면 `OBSERVABILITY` 없이 `./scripts/run_with_gateway.sh`를 돌린다(계측 no-op).
```

- [ ] **Step 4: Commit**

```bash
git add scripts/run_with_gateway.sh README.md
git commit -m "docs: OBSERVABILITY 모드 기동 경로와 관측 스택 검증 절차 추가"
```

---

### Task 7: end-to-end 수동 검증 + spec에 실측 기록

**Files:**
- Modify: `docs/superpowers/specs/2026-06-29-agentgateway-observability-design.md` (§6 검증 결과 추가)

**Interfaces:**
- Consumes: Task 1~6 전부.
- Produces: spec §6에 실측 검증 결과 기록(이전 spec들의 §8/§9-E와 동일한 패턴).

> 이 Task는 실제 OpenAI/Tavily 키와 Docker가 필요하다. 키/Docker가 없으면 검증 가능한 항목(메트릭 노출·하위호환)만 수행하고 나머지는 절차만 기록한다.

- [ ] **Step 1: 전체 스택 기동**

Run:
```bash
docker compose -f docker-compose.observability.yml up -d && sleep 8
OBSERVABILITY=1 ./scripts/run_with_gateway.sh &
sleep 4
```
Expected: 게이트웨이/백엔드/오케스트레이터가 뜨고 `observability ON` 로그가 보임.

- [ ] **Step 2: 검증 1 — 메트릭 노출·스크랩**

Run:
```bash
curl -s -N -X POST http://127.0.0.1:9000/run -H 'content-type: application/json' \
  -d '{"task":"양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"}' | head -5
sleep 2
echo "--- gateway metrics (A2A series) ---"
curl -s http://127.0.0.1:15020/metrics | grep 'agentgateway_requests_total{protocol="a2a"' | head
echo "--- prometheus target ---"
curl -s 'http://localhost:9090/api/v1/targets' | grep -o '"health":"[a-z]*"' | head -1
```
Expected: `final` SSE가 나오고, `agentgateway_requests_total{protocol="a2a",...route="default/route0"...,status="200"}` 시리즈가 보이며, Prometheus 타깃 `"health":"up"`.

- [ ] **Step 3: 검증 2 — 대시보드**

수동: Grafana(http://localhost:3000) → "A2A via agentgateway" 대시보드에서 4패널(호출량·p95·에러율·route×status)에 값이 그려지는지 확인. 스크린샷/요약을 기록.

- [ ] **Step 4: 검증 3 — end-to-end 트레이스**

수동: Jaeger UI(http://localhost:16686) → service `orchestrator` 검색 → 방금 `/run` trace를 열어
`orchestrator → gateway(/research) → research → gateway(/summarizer) → summarizer`가 **한 trace-id**로
묶이는지 확인. (만약 어느 홉에서 끊기면 어디서 traceparent가 유실되는지 기록 — spec §5 약점 항목 갱신.)

- [ ] **Step 5: 검증 4 — 하위호환(관측 OFF)**

Run:
```bash
# 관측 스택/OTEL 없이 기동
./scripts/run_with_gateway.sh &
sleep 4
curl -s -N -X POST http://127.0.0.1:9000/run -H 'content-type: application/json' \
  -d '{"task":"테스트"}' | head -3
```
Expected: OTEL 미설정·Jaeger 무관하게 `tool_call`/`final` SSE 정상 — 패스스루가 그대로 동작.

- [ ] **Step 6: 자동 테스트 전체 통과 확인**

Run: `.venv/bin/python -m pytest -v`
Expected: 전체 PASS (기존 + `test_telemetry.py`).

- [ ] **Step 7: spec에 검증 결과 기록 + commit**

`docs/superpowers/specs/2026-06-29-agentgateway-observability-design.md`의 §6 아래에 "검증 결과 (실측, 2026-06-29)" 소절을 추가해 검증 1~4의 실측(메트릭 시리즈, 대시보드, trace 묶임 여부, 하위호환)을 기록한다. trace가 끊긴 홉이 있으면 §5 약점 항목도 갱신한다.

```bash
git add docs/superpowers/specs/2026-06-29-agentgateway-observability-design.md
git commit -m "docs: observability end-to-end 검증 결과를 spec에 실측 기록"
```

- [ ] **Step 8: 정리**

Run:
```bash
docker compose -f docker-compose.observability.yml down
# 백그라운드 프로세스 정리 (run_with_gateway.sh의 trap이 Ctrl-C로 정리하지만, 백그라운드 기동 시 수동 kill)
pkill -f "agentgateway -f config/agentgateway.yaml" || true
pkill -f "python -m agents" || true
pkill -f "python -m orchestrator" || true
```

---

## Self-Review

**1. Spec coverage** (spec 각 절 → task 매핑):
- §1 목표/확정 결정 → 전 Task의 Global Constraints + on/off 가드(Task 1·3·6).
- §2-A 메트릭 무설정 노출 → Task 5(스크랩) + Task 7 검증 1. §2-B 게이트웨이 tracing → Task 4. §2-C Python 계측 → Task 1·3.
- §3 아키텍처 → Task 4(tracing) + Task 5(스택).
- §4-a config.tracing → Task 4. §4-b telemetry.py → Task 1. §4-c 진입점 → Task 3. §4-d compose/provisioning → Task 5. §4-e extra → Task 2. §4-f 스크립트 → Task 6.
- §5 trace 흐름/약점 → Task 7 검증 3(끊김 시 기록). §6 검증 4종 → Task 7 Step 2~5. §7 범위 밖 → 계측 없음(수동 span 금지)으로 준수.
- 갭 없음.

**2. Placeholder scan**: "TBD"/"적절히"/"위와 유사" 없음. 모든 코드 step에 실제 코드 포함. Task 7의 수동 검증(대시보드/Jaeger UI)은 본질적으로 사람이 보는 것이라 "수동"으로 명시 — 절차/기대값은 구체화됨.

**3. Type consistency**: `setup_telemetry(service_name: str) -> bool`이 Task 1 정의 ↔ Task 3 사용에서 일치(`enabled = setup_telemetry(...)` → `if enabled:`). `build_starlette_app(card, executor)`/`build_app()`는 기존 시그니처 그대로 사용. 메트릭 이름(`agentgateway_requests_total`, `agentgateway_request_duration_seconds_bucket`)이 Task 5 대시보드 ↔ Task 7 검증 ↔ spec §2-A에서 일치. 라벨 `protocol="a2a"`, `route`, `status` 일관.

이상 없음.
