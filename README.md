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

# 2) 다른 터미널에서 오케스트레이터를 SSE 서버로 기동
python -m orchestrator   # http://127.0.0.1:9000

# 3) 진행 상황을 SSE로 받으며 과업 실행
curl -N -X POST http://127.0.0.1:9000/run \
  -H 'content-type: application/json' \
  -d '{"task":"양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"}'
```

응답의 각 줄은 `data: {...}` SSE 이벤트다. `type`은 `tool_call`(에이전트 호출
시작), `tool_result`(결과 관찰), `final`(최종 답변; `truncated`가 true면 step
limit으로 강제 종합된 부분 답변), `error`(스트림 중 예외) 중 하나다.

각 에이전트의 Agent Card는
`http://127.0.0.1:9001/.well-known/agent-card.json` 에서 확인할 수 있다.

## (선택) agentgateway 프록시 모드

[agentgateway](https://agentgateway.dev)를 research/summarizer 앞단에 **단일 포트 +
경로 기반 프록시**로 끼워, 오케스트레이터가 게이트웨이를 통해 에이전트를 호출하게 한다.
게이트웨이 바이너리는 수동 설치한다(설치 안내는 위 링크 참조).

```bash
# 백엔드+게이트웨이+오케스트레이터를 한 번에 기동
./scripts/run_with_gateway.sh
```

매핑: `:8080/research/* → :9001`(research), `:8080/summarizer/* → :9002`(summarizer).
게이트웨이가 path prefix(`/research`, `/summarizer`)를 strip해 백엔드 `/`로 전달한다.
게이트웨이 설정은 `config/agentgateway.yaml`에 있다.

환경변수 두 종류가 각기 다른 프로세스에 주입된다:

- `RESEARCH_PUBLIC_URL` / `SUMMARIZER_PUBLIC_URL` — **백엔드**에 주입. 카드가 광고할
  게이트웨이 주소(prefix 포함, 끝 슬래시 O). 미설정 시 백엔드 직접 주소를 광고한다.
- `RESEARCH_AGENT_URL` / `SUMMARIZER_AGENT_URL` — **오케스트레이터**에 주입. 호출 목적지인
  게이트웨이 주소(prefix 포함, 끝 슬래시 X). 미설정 시 백엔드를 직접 호출한다.

게이트웨이를 통해 받은 카드가 prefix 포함 게이트웨이 주소를 광고하는지 확인
(`supportedInterfaces[0].url`이 `http://127.0.0.1:8080/research/`이어야 한다):

```bash
curl -s http://127.0.0.1:8080/research/.well-known/agent-card.json
```

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

## 테스트

```bash
pytest -v
```

테스트는 OpenAI/Tavily 호출을 가짜로 대체해 네트워크 없이 돈다.

## 구조

- `common/` — AgentCard 빌더, LangGraph→A2A executor 어댑터, 서버 조립
- `agents/<name>/` — 에이전트별 graph + card + server 진입점
- `orchestrator/` — discovery, A2A 클라이언트, ReAct 실행 흐름, SSE 서버

새 에이전트 추가: `agents/<name>/`에 `graph.py`/`card.py`/`__main__.py`를
작성하고 `orchestrator/registry.py`의 `AGENT_URLS`에 URL 한 줄 추가.
