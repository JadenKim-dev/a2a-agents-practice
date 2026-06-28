# agentgateway 접근 A (단일 포트 path-prefix 라우팅) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 접근 B(에이전트당 게이트웨이 포트)를 단일 게이트웨이 포트(:8080) + path-prefix 라우팅(접근 A)으로 교체한다.

**Architecture:** agentgateway 단일 bind(:8080) 뒤에서 `/research/*`·`/summarizer/*` path prefix로 백엔드를 분기하고, `urlRewrite.path.prefix: /`로 prefix를 strip해 백엔드(`:9001`/`:9002`의 `/`)로 전달한다. 카드 url(`*_PUBLIC_URL`)·레지스트리 url(`*_AGENT_URL`)은 접근 B에서 이미 환경변수로 외부화돼 있어 **코드 변경은 없고**, config·스크립트·README가 주입하는 url 값만 단일 포트 + prefix로 바뀐다.

**Tech Stack:** agentgateway v1.3.1 (외부 Rust 바이너리, `~/.local/bin`), a2a-sdk 1.1.0 (Python), 기존 PoC 스택(FastAPI/uvicorn, LangGraph, OpenAI gpt-4o-mini, Tavily).

## Global Constraints

- agentgateway 버전: **v1.3.1** (darwin-arm64). config 플래그는 `-f`. 스키마 검증은 `--validate-only`.
- 게이트웨이 단일 포트: **:8080**. 백엔드는 불변(research :9001, summarizer :9002, 둘 다 `/`·`/.well-known/...`에서 리슨).
- 카드 광고 url(`*_PUBLIC_URL`)은 **끝 슬래시 O** (`http://127.0.0.1:8080/research/`).
- 오케스트레이터 호출 url(`*_AGENT_URL`)은 **끝 슬래시 X** (`http://127.0.0.1:8080/research`) — `A2ACardResolver`가 `rstrip('/')` 후 카드 경로를 조립하므로.
- 접근 B는 git history와 spec §8에 검증 기록으로 남긴다. 접근 A는 spec §9 기준으로 구현한다.
- 게이트웨이는 외부 바이너리라 CI에 묶지 않는다. 검증은 **로컬 수동 + 절차/결과 문서화**.
- 문서 작성은 한글. docstring/주석 한글 선호.
- 작업 브랜치: `feature/agentgateway-path-routing` (이미 생성됨, spec 커밋 완료).

---

## File Structure

| 파일 | 변경 | 책임 |
|---|---|---|
| `config/agentgateway.yaml` | Modify (전면 교체) | 단일 bind :8080 + path-prefix 라우팅 + prefix strip |
| `scripts/run_with_gateway.sh` | Modify | 백엔드/오케스트레이터에 주입하는 url 값을 단일 포트 + prefix로 |
| `README.md` | Modify (line 38-64 섹션) | 게이트웨이 모드 안내를 접근 A로 갱신 |
| `docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md` | Modify (§9-D 실측 추가) | end-to-end 검증 결과 기록 |

코드 파일(`agents/*/card.py`, `orchestrator/registry.py`)은 변경 없음 — 이미 외부화돼 있어 주입 값만 바뀐다.

---

### Task 1: agentgateway config를 접근 A로 교체

**Files:**
- Modify: `config/agentgateway.yaml` (전체 교체)

**Interfaces:**
- Consumes: 백엔드 `127.0.0.1:9001`(research), `127.0.0.1:9002`(summarizer) — 불변.
- Produces: 게이트웨이 단일 진입점 `127.0.0.1:8080`, 라우트 `/research/*`→9001, `/summarizer/*`→9002 (prefix strip).

- [ ] **Step 1: config를 접근 A 내용으로 전면 교체**

`config/agentgateway.yaml`의 전체 내용을 아래로 교체한다:

```yaml
# research/summarizer A2A 서버 앞단에 두는 단일 포트 + path-prefix 프록시 설정(접근 A).
# :8080/research/*   → :9001 (research),   prefix /research 를 strip 후 백엔드 / 로 전달.
# :8080/summarizer/* → :9002 (summarizer), prefix /summarizer 를 strip 후 백엔드 / 로 전달.
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

- [ ] **Step 2: 게이트웨이 스키마 검증 (테스트 역할)**

Run: `agentgateway -f config/agentgateway.yaml --validate-only`
Expected: `Configuration is valid!` (다른 출력/에러 없이)

- [ ] **Step 3: Commit**

```bash
git add config/agentgateway.yaml
git commit -m "feat: agentgateway config를 접근 A(단일 포트 :8080 + path-prefix strip)로 교체"
```

---

### Task 2: run_with_gateway.sh를 접근 A로 교체

**Files:**
- Modify: `scripts/run_with_gateway.sh`

**Interfaces:**
- Consumes: Task 1의 `config/agentgateway.yaml`(단일 :8080), 백엔드 모듈(`python -m agents.research`/`agents.summarizer`), 오케스트레이터(`python -m orchestrator`).
- Produces: 한 번에 기동되는 접근 A 전체 스택. 백엔드엔 prefix 포함 `*_PUBLIC_URL`, 오케스트레이터엔 prefix 포함 `*_AGENT_URL` 주입.

- [ ] **Step 1: 스크립트의 url 주입부를 단일 포트 + prefix로 교체**

`scripts/run_with_gateway.sh`에서 백엔드 기동부(현재 `:8001/`, `:8002/`를 광고)와 오케스트레이터 기동부(현재 `:8001`, `:8002` 호출)를 아래처럼 바꾼다. 백엔드 `*_PUBLIC_URL`은 끝 슬래시 O, 오케스트레이터 `*_AGENT_URL`은 끝 슬래시 X.

기존:
```bash
RESEARCH_PUBLIC_URL="http://127.0.0.1:8001/" python -m agents.research &
RESEARCH_PID=$!
SUMMARIZER_PUBLIC_URL="http://127.0.0.1:8002/" python -m agents.summarizer &
SUMMARIZER_PID=$!
```
교체:
```bash
RESEARCH_PUBLIC_URL="http://127.0.0.1:8080/research/" python -m agents.research &
RESEARCH_PID=$!
SUMMARIZER_PUBLIC_URL="http://127.0.0.1:8080/summarizer/" python -m agents.summarizer &
SUMMARIZER_PID=$!
```

기존:
```bash
RESEARCH_AGENT_URL="http://127.0.0.1:8001" \
SUMMARIZER_AGENT_URL="http://127.0.0.1:8002" \
python -m orchestrator &
```
교체:
```bash
RESEARCH_AGENT_URL="http://127.0.0.1:8080/research" \
SUMMARIZER_AGENT_URL="http://127.0.0.1:8080/summarizer" \
python -m orchestrator &
```

- [ ] **Step 2: 시작 로그 메시지를 단일 포트로 갱신**

기존:
```bash
echo "research→:8001, summarizer→:8002 (gateway), orchestrator :9000"
```
교체:
```bash
echo "research→:8080/research, summarizer→:8080/summarizer (gateway), orchestrator :9000"
```

- [ ] **Step 3: bash 문법 검증 (테스트 역할)**

Run: `bash -n scripts/run_with_gateway.sh`
Expected: 출력 없음, exit 0 (문법 에러 없음).

또한 교체가 누락 없이 됐는지 확인:
Run: `grep -nE ':800[12]' scripts/run_with_gateway.sh`
Expected: 출력 없음 (접근 B 포트 :8001/:8002가 더 이상 없어야 함).

- [ ] **Step 4: Commit**

```bash
git add scripts/run_with_gateway.sh
git commit -m "feat: run_with_gateway.sh를 접근 A(단일 포트 + path-prefix url 주입)로 교체"
```

---

### Task 3: README 게이트웨이 섹션을 접근 A로 갱신

**Files:**
- Modify: `README.md` (현재 line 38-64 "(선택) agentgateway 프록시 모드" 섹션)

**Interfaces:**
- Consumes: Task 1·2의 결과(단일 :8080, prefix 라우팅).
- Produces: 접근 A 기준 사용자 안내.

- [ ] **Step 1: README 섹션을 접근 A 내용으로 교체**

`README.md`의 "(선택) agentgateway 프록시 모드" 섹션(소제목 `## (선택) agentgateway 프록시 모드`부터 그 다음 소제목 `## 테스트` 직전까지)을 아래로 교체한다. `## 테스트` 소제목 자체는 건드리지 않는다.

```markdown
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
```

- [ ] **Step 2: 갱신 검증 (테스트 역할)**

Run: `grep -nE ':800[12]|포트 1:1' README.md`
Expected: 출력 없음 (접근 B의 포트 :8001/:8002·"포트 1:1" 표현이 더 이상 없어야 함).

Run: `grep -c '8080/research' README.md`
Expected: `2` 이상 (매핑 설명 + curl 예시).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README 게이트웨이 모드 안내를 접근 A(단일 포트 path-prefix)로 갱신"
```

---

### Task 4: end-to-end 수동 검증 + spec §9-D에 실측 기록

게이트웨이는 외부 바이너리이고 message/send는 실제 OpenAI/Tavily 키를 쓰므로, 이 검증은 pytest가 아닌 **실제 스택 기동 + 관찰**이다. spec §9-D 검증 4종을 단일 포트 기준으로 수행한다. `.env`에 `OPENAI_API_KEY`·`TAVILY_API_KEY`가 있어야 한다.

> **주의:** 사용자가 접근 B 스택(:8001/:8002/:9000-9002)을 이미 띄워뒀을 수 있다. 검증 전 `lsof -nP -sTCP:LISTEN -iTCP:9000 -iTCP:9001 -iTCP:9002 -iTCP:8001 -iTCP:8002` 로 점유를 확인하고, 떠 있으면 그 스택을 멈춘 뒤(사용자에게 확인) 진행한다. 같은 포트(:9000-9002)를 재사용하므로 충돌하면 검증이 잘못된 스택을 친다.

**Files:**
- Modify: `docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md` (§9-D에 실측 결과 추가)

**Interfaces:**
- Consumes: Task 1·2의 결과(`config/agentgateway.yaml`, `run_with_gateway.sh`), `.env` 키.
- Produces: 검증된 접근 A 스택 + spec에 기록된 실측.

- [ ] **Step 1: 포트 점유 확인 후 전체 스택 기동**

Run: `lsof -nP -sTCP:LISTEN -iTCP:9000 -iTCP:9001 -iTCP:9002 -iTCP:8080 2>/dev/null`
- 출력이 있으면(기존 스택 점유) 사용자에게 알리고 멈춘 뒤 진행.
- 비어 있으면 기동:

Run: `./scripts/run_with_gateway.sh` (별도 터미널/백그라운드. 백엔드·게이트웨이·오케스트레이터가 뜰 때까지 ~3초 대기).
Expected 로그: `research→:8080/research, summarizer→:8080/summarizer (gateway), orchestrator :9000` 와 게이트웨이의 `started bind bind="bind/8080"`.

- [ ] **Step 2: 검증 1 — 카드 discovery + prefix url 광고 (양 에이전트)**

Run:
```bash
curl -s -o /dev/null -w "research card HTTP %{http_code}\n" http://127.0.0.1:8080/research/.well-known/agent-card.json
curl -s http://127.0.0.1:8080/research/.well-known/agent-card.json | python3 -c "import sys,json; c=json.load(sys.stdin); print('research url:', [i['url'] for i in c['supportedInterfaces']])"
curl -s -o /dev/null -w "summarizer card HTTP %{http_code}\n" http://127.0.0.1:8080/summarizer/.well-known/agent-card.json
curl -s http://127.0.0.1:8080/summarizer/.well-known/agent-card.json | python3 -c "import sys,json; c=json.load(sys.stdin); print('summarizer url:', [i['url'] for i in c['supportedInterfaces']])"
```
Expected:
```
research card HTTP 200
research url: ['http://127.0.0.1:8080/research/']
summarizer card HTTP 200
summarizer url: ['http://127.0.0.1:8080/summarizer/']
```

- [ ] **Step 3: 검증 4 — path 격리 (미정의 prefix는 404, 라우트는 안 섞임)**

Run:
```bash
curl -s -o /dev/null -w "unknown prefix HTTP %{http_code}\n" http://127.0.0.1:8080/unknown/.well-known/agent-card.json
curl -s http://127.0.0.1:8080/summarizer/.well-known/agent-card.json | python3 -c "import sys,json; print('name@/summarizer:', json.load(sys.stdin)['name'])"
```
Expected:
```
unknown prefix HTTP 404
name@/summarizer: summarizer
```
(`/summarizer` 라우트가 research가 아닌 summarizer 카드를 반환 = 라우트가 안 섞임.)

- [ ] **Step 4: 검증 2 — 오케스트레이터 end-to-end (실제 키 호출)**

Run:
```bash
curl -sN -X POST http://127.0.0.1:9000/run -H 'Content-Type: application/json' \
  -d '{"input":"Briefly research the latest on Linux Foundation and summarize."}' | tee /tmp/path_e2e.sse
```
Expected: SSE 스트림에 `tool_call`(research) → `tool_result` → `final` 이벤트가 나오고, 에러·`[discover] skip` 없이 최종 답변이 온다.

게이트웨이 로그(스택 stdout)에 단일 포트 + prefix 라우팅 + A2A 인지가 찍히는지 확인:
Expected 로그 패턴: `http.path=/research/ ... a2a.method=SendStreamingMessage http.status=200` (그리고 summarizer가 호출됐다면 `http.path=/summarizer/ ...`).

- [ ] **Step 5: 검증 3 — 스트리밍 중간 이벤트 점진 도착 (버퍼링 없음)**

Run:
```bash
grep -nE '"type"|path|tool_call|tool_result|final' /tmp/path_e2e.sse | head -20
```
Expected: 서브 에이전트 진행 이벤트(`path:["research"]` 류 `status_update`)가 응답 중간에 나타나고, 모든 이벤트가 끝에 몰리지 않는다. (스트리밍 중 `tee`로 점진 출력됐다면 버퍼링 없음.)

- [ ] **Step 6: spec §9-D에 실측 결과 기록**

`docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md`의 §9-D 검증 4종 목록 **아래에** 실측 결과 블록을 추가한다. Step 2~5에서 실제로 관찰한 값(HTTP 코드, url, 게이트웨이 로그의 `a2a.method`·`http.path`·`http.status`, 이벤트 타임라인)을 §8의 형식("**검증 N — ...: ✅**" + 근거)을 따라 적는다. 추측이 아니라 관찰한 실제 출력만 적는다.

추가할 블록의 형식(값은 실측으로 채움):
```markdown
### 9-F. 검증 결과 (실측, YYYY-MM-DD)

프로덕션 config(:8080)로 전체 스택을 띄워 §9-D 4종을 모두 수행했다.

**검증 1 — 카드 discovery + prefix url 광고: ✅**
- `curl :8080/research/.well-known/agent-card.json` → HTTP <실측>, `supportedInterfaces[0].url == <실측>`.
- summarizer도 `:8080/summarizer/...` 동일.

**검증 4 — path 격리: ✅**
- 미정의 prefix `:8080/unknown/...` → HTTP <실측>. `/summarizer` 라우트는 summarizer 카드 반환(안 섞임).

**검증 2 — 오케스트레이터 end-to-end: ✅**
- `POST :9000/run` → `tool_call`→`tool_result`→`final` SSE 정상. 게이트웨이 로그:
  `<실측: http.path=/research/ ... a2a.method=SendStreamingMessage http.status=200 ...>`.

**검증 3 — 스트리밍 중간 이벤트 점진 도착: ✅**
- 이벤트 도착 타임라인: <실측>. 마지막에 몰리지 않음 — SSE 버퍼링 없음.

**결론**: 접근 A(단일 포트 + path-prefix strip)에서 agentgateway는 a2a-sdk 1.1.0의
카드 discovery·스트리밍 message/send·SSE 중간 이벤트를 모두 투명 중계한다. 코드 변경 없이
config/스크립트의 url 값만 단일 포트 + prefix로 바꿔 전환 완료.
```

- [ ] **Step 7: 스택 정리 + Commit**

스택을 띄운 방식대로 종료한다(`run_with_gateway.sh`는 Ctrl-C 시 `trap cleanup`으로 정리; 백그라운드로 띄웠으면 해당 PID들을 kill).

```bash
git add docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md
git commit -m "docs: 접근 A end-to-end 검증 결과를 spec §9-F에 실측 기록"
```

---

## Self-Review

**1. Spec coverage** (spec §9 대비):
- §9-C (a) config 교체 → Task 1 ✅
- §9-C (b) card.py 변경 없음 → 코드 변경 없음으로 명시, 별도 태스크 불필요 ✅
- §9-C (c) registry.py 변경 없음 → 동일 ✅
- §9-C (d) run_with_gateway.sh 교체 → Task 2 ✅
- §9-D 검증 4종 → Task 4 Step 2~5 ✅
- README 갱신 → spec엔 없던 항목이나 접근 B 안내가 README에 있어 갱신 필요 → Task 3으로 보강 ✅
- §9-A 부수확인(admin 포트 off는 스파이크 한정, 프로덕션 config엔 미적용) → config에 adminAddr 미포함으로 반영(Task 1) ✅

**2. Placeholder scan:** Task 4 §9-F 블록의 `<실측>`은 의도적 — 실제 관찰값을 채우는 자리이며, "추측 말고 관찰값만"이라고 명시. 그 외 TBD/TODO 없음 ✅

**3. Type/값 일관성:** 끝 슬래시 규칙(`*_PUBLIC_URL` O / `*_AGENT_URL` X)이 Global Constraints·Task 2·Task 3에서 일관. 포트 :8080, prefix `/research`·`/summarizer`가 전 태스크에서 일치 ✅
