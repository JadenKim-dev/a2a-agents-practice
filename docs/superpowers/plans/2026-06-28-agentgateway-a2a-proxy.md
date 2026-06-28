# agentgateway A2A 프록시 (PoC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** agentgateway를 research/summarizer A2A 서버 앞단에 포트 1:1 프록시(`:8001→:9001`, `:8002→:9002`)로 끼우고, 오케스트레이터 end-to-end 흐름이 게이트웨이를 통과해도 깨지지 않음을 검증한다.

**Architecture:** 카드가 광고하는 url과 오케스트레이터의 호출 목적지 url을 환경변수로 외부화한다. 게이트웨이 모드에서는 둘 다 게이트웨이 주소를 가리키게 하고, 미설정 시 기존 백엔드 주소를 기본값으로 둬 하위호환을 유지한다. 백엔드 서버의 bind 포트(9001/9002)는 바뀌지 않는다 — 카드가 광고하는 url만 바뀐다.

**Tech Stack:** Python 3.11, a2a-sdk 1.1.0(protobuf 기반), agentgateway(외부 Rust 바이너리, 수동 설치), pytest.

## Global Constraints

- a2a-sdk는 `==1.1.0` (protobuf 타입 기반). 카드 url은 `supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=...)]`에 들어간다.
- 카드가 광고하는 url(`*_PUBLIC_URL`)과 서버 bind 포트는 별개다. 서버는 여전히 `127.0.0.1:9001`/`:9002`에 바인딩한다.
- 환경변수 미설정 시 기존 백엔드 주소를 기본값으로 → 게이트웨이 없이 직접 실행하는 기존 흐름이 그대로 동작해야 한다.
- 게이트웨이 포트: research `:8001`, summarizer `:8002`.
- docstring/주석은 한글로, 책임을 서술하는 평서문("~한다")으로 작성한다.
- 테스트는 `// given / when / then` 대신 한글 `# given` `# when` `# then`을 쓰고, 입력 리터럴을 `it` 블록 안에 직접 둔다.

---

### Task 1: 카드 광고 URL을 환경변수로 외부화 (research, summarizer)

카드가 광고하는 url을 환경변수에서 읽되, 미설정 시 기존 백엔드 주소를 기본값으로 둔다. 게이트웨이 모드에서 카드가 게이트웨이 주소를 광고하게 만드는 변경이다.

**Files:**
- Modify: `agents/research/card.py:4`
- Modify: `agents/summarizer/card.py:4`
- Test: `tests/test_card_public_url.py` (Create)

**Interfaces:**
- Consumes: `build_agent_card(name, description, url, skill_id, skill_name, skill_description, skill_tags)` (변경 없음).
- Produces: 환경변수 `RESEARCH_PUBLIC_URL` 설정 시 `RESEARCH_CARD.supported_interfaces[0].url`이 그 값이 됨. `SUMMARIZER_PUBLIC_URL`도 동일.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_card_public_url.py`:

```python
"""카드 광고 url이 환경변수로 외부화되는지 검증한다."""
import importlib

import agents.research.card as research_card
import agents.summarizer.card as summarizer_card


def test_research_card_url_defaults_to_backend_when_env_unset(monkeypatch):
    # given
    monkeypatch.delenv("RESEARCH_PUBLIC_URL", raising=False)

    # when
    module = importlib.reload(research_card)

    # then
    assert module.RESEARCH_CARD.supported_interfaces[0].url == "http://127.0.0.1:9001/"


def test_research_card_url_uses_env_when_set(monkeypatch):
    # given
    monkeypatch.setenv("RESEARCH_PUBLIC_URL", "http://127.0.0.1:8001/")

    # when
    module = importlib.reload(research_card)

    # then
    assert module.RESEARCH_CARD.supported_interfaces[0].url == "http://127.0.0.1:8001/"


def test_summarizer_card_url_defaults_to_backend_when_env_unset(monkeypatch):
    # given
    monkeypatch.delenv("SUMMARIZER_PUBLIC_URL", raising=False)

    # when
    module = importlib.reload(summarizer_card)

    # then
    assert module.SUMMARIZER_CARD.supported_interfaces[0].url == "http://127.0.0.1:9002/"


def test_summarizer_card_url_uses_env_when_set(monkeypatch):
    # given
    monkeypatch.setenv("SUMMARIZER_PUBLIC_URL", "http://127.0.0.1:8002/")

    # when
    module = importlib.reload(summarizer_card)

    # then
    assert module.SUMMARIZER_CARD.supported_interfaces[0].url == "http://127.0.0.1:8002/"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_card_public_url.py -v`
Expected: FAIL — `test_*_uses_env_when_set`가 기존 하드코딩 url을 반환해 AssertionError.

- [ ] **Step 3: 최소 구현 — research card**

`agents/research/card.py`의 `RESEARCH_URL` 한 줄을 교체:

```python
"""Research 에이전트의 A2A AgentCard를 정의한다."""
import os

from common.agent_card import build_agent_card

RESEARCH_URL = os.environ.get("RESEARCH_PUBLIC_URL", "http://127.0.0.1:9001/")

RESEARCH_CARD = build_agent_card(
    name="research",
    description="Researches a topic using web search and returns a factual briefing.",
    url=RESEARCH_URL,
    skill_id="research",
    skill_name="Web Research",
    skill_description="Find current information on a topic and summarize the findings.",
    skill_tags=["research", "web-search"],
)
```

- [ ] **Step 4: 최소 구현 — summarizer card**

`agents/summarizer/card.py`의 `SUMMARIZER_URL` 한 줄을 교체:

```python
"""Summarizer 에이전트의 A2A AgentCard를 정의한다."""
import os

from common.agent_card import build_agent_card

SUMMARIZER_URL = os.environ.get("SUMMARIZER_PUBLIC_URL", "http://127.0.0.1:9002/")

SUMMARIZER_CARD = build_agent_card(
    name="summarizer",
    description="Summarizes provided text into a concise multi-paragraph summary.",
    url=SUMMARIZER_URL,
    skill_id="summarize",
    skill_name="Summarize Text",
    skill_description="Condense provided text into a faithful short summary.",
    skill_tags=["summarize", "text"],
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_card_public_url.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: 기존 테스트 회귀 없음 확인**

Run: `pytest -q`
Expected: 전체 PASS (기존 `test_agent_card.py`는 `build_agent_card`를 직접 호출하므로 영향 없음).

- [ ] **Step 7: 커밋**

```bash
git add agents/research/card.py agents/summarizer/card.py tests/test_card_public_url.py
git commit -m "feat: 카드 광고 url을 환경변수로 외부화 (게이트웨이 주소 광고용)"
```

---

### Task 2: 오케스트레이터 AGENT_URLS를 환경변수로 외부화

오케스트레이터의 호출 목적지를 환경변수에서 읽되, 미설정 시 기존 백엔드 주소를 기본값으로 둔다. 게이트웨이 모드에서 오케스트레이터가 게이트웨이를 호출하게 만드는 변경이다.

**Files:**
- Modify: `orchestrator/registry.py:7-10`
- Test: `tests/test_registry.py` (Create)

**Interfaces:**
- Consumes: 없음.
- Produces: `AGENT_URLS["research"]`가 `RESEARCH_AGENT_URL` 설정 시 그 값, 미설정 시 `http://127.0.0.1:9001`. `summarizer`는 `SUMMARIZER_AGENT_URL` / `http://127.0.0.1:9002`. `discover_agents(http)` 시그니처는 불변.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_registry.py`:

```python
"""오케스트레이터 AGENT_URLS가 환경변수로 외부화되는지 검증한다."""
import importlib

import orchestrator.registry as registry


def test_agent_urls_default_to_backend_when_env_unset(monkeypatch):
    # given
    monkeypatch.delenv("RESEARCH_AGENT_URL", raising=False)
    monkeypatch.delenv("SUMMARIZER_AGENT_URL", raising=False)

    # when
    module = importlib.reload(registry)

    # then
    assert module.AGENT_URLS["research"] == "http://127.0.0.1:9001"
    assert module.AGENT_URLS["summarizer"] == "http://127.0.0.1:9002"


def test_agent_urls_use_env_when_set(monkeypatch):
    # given
    monkeypatch.setenv("RESEARCH_AGENT_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("SUMMARIZER_AGENT_URL", "http://127.0.0.1:8002")

    # when
    module = importlib.reload(registry)

    # then
    assert module.AGENT_URLS["research"] == "http://127.0.0.1:8001"
    assert module.AGENT_URLS["summarizer"] == "http://127.0.0.1:8002"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL — `test_agent_urls_use_env_when_set`가 하드코딩 주소를 반환해 AssertionError.

- [ ] **Step 3: 최소 구현**

`orchestrator/registry.py`의 `AGENT_URLS` 정의(7-10행)를 교체. `import os`를 상단에 추가:

```python
"""알려진 A2A 에이전트 URL 목록을 두고 카드를 discovery한다."""
import os

import httpx

from a2a.client import A2ACardResolver
from a2a.types import AgentCard

AGENT_URLS: dict[str, str] = {
    "research": os.environ.get("RESEARCH_AGENT_URL", "http://127.0.0.1:9001"),
    "summarizer": os.environ.get("SUMMARIZER_AGENT_URL", "http://127.0.0.1:9002"),
}
```

(`discover_agents` 함수 본문은 변경하지 않는다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_registry.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: 기존 테스트 회귀 없음 확인**

Run: `pytest -q`
Expected: 전체 PASS.

- [ ] **Step 6: 커밋**

```bash
git add orchestrator/registry.py tests/test_registry.py
git commit -m "feat: 오케스트레이터 AGENT_URLS를 환경변수로 외부화 (게이트웨이 호출용)"
```

---

### Task 3: agentgateway config 작성

게이트웨이가 두 포트(8001/8002)를 각 백엔드(9001/9002)로 a2a 패스스루 프록시하도록 config를 둔다. yaml 정적 파일이므로 단위 테스트 대신 yaml 유효성 검사로 검증한다.

**Files:**
- Create: `config/agentgateway.yaml`
- Test: 명령형 검증 (아래 Step 2).

**Interfaces:**
- Consumes: 백엔드 `127.0.0.1:9001`, `127.0.0.1:9002`.
- Produces: 게이트웨이 리스너 `:8001`, `:8002`.

- [ ] **Step 1: config 작성**

`config/agentgateway.yaml`:

```yaml
# research/summarizer A2A 서버 앞단에 두는 포트 1:1 패스스루 프록시 설정.
# :8001 → :9001 (research), :8002 → :9002 (summarizer).
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

- [ ] **Step 2: yaml 유효성 검사**

Run: `python -c "import yaml, sys; d = yaml.safe_load(open('config/agentgateway.yaml')); assert [b['port'] for b in d['binds']] == [8001, 8002]; assert [b['listeners'][0]['routes'][0]['backends'][0]['host'] for b in d['binds']] == ['127.0.0.1:9001', '127.0.0.1:9002']; print('ok')"`
Expected: `ok`
(참고: `yaml`은 `python-dotenv`의 전이 의존이 아니므로, 미설치 시 `pip install pyyaml` 후 재실행하거나 이 검사를 건너뛰고 Step 3의 게이트웨이 기동으로 대체한다.)

- [ ] **Step 3: 커밋**

```bash
git add config/agentgateway.yaml
git commit -m "feat: agentgateway 포트 1:1 A2A 프록시 config 추가"
```

---

### Task 4: 게이트웨이 모드 기동 스크립트

게이트웨이를 끼운 전체 스택을 한 번에 띄우는 편의 스크립트. 두 종류의 환경변수를 올바른 프로세스에 주입한다: `*_PUBLIC_URL`은 백엔드(카드 광고용), `*_AGENT_URL`은 오케스트레이터(호출 목적지용). 게이트웨이 바이너리는 수동 설치를 가정한다.

**Files:**
- Create: `scripts/run_with_gateway.sh`
- Test: bash 문법 검사 (아래 Step 2).

**Interfaces:**
- Consumes: `config/agentgateway.yaml`(Task 3), `agentgateway` 바이너리(PATH에 있다고 가정).
- Produces: 없음(실행 스크립트).

- [ ] **Step 1: 스크립트 작성**

`scripts/run_with_gateway.sh`:

```bash
#!/usr/bin/env bash
# 게이트웨이를 끼운 전체 스택을 띄운다.
#   백엔드는 카드가 게이트웨이 주소를 광고하도록 *_PUBLIC_URL과 함께,
#   오케스트레이터는 게이트웨이를 호출하도록 *_AGENT_URL과 함께 기동한다.
#   agentgateway 바이너리는 PATH에 설치되어 있다고 가정한다.
set -euo pipefail

if ! command -v agentgateway >/dev/null 2>&1; then
  echo "agentgateway 바이너리를 PATH에서 찾을 수 없습니다. https://agentgateway.dev 설치 안내를 참고하세요." >&2
  exit 1
fi

RESEARCH_PUBLIC_URL="http://127.0.0.1:8001/" python -m agents.research &
RESEARCH_PID=$!
SUMMARIZER_PUBLIC_URL="http://127.0.0.1:8002/" python -m agents.summarizer &
SUMMARIZER_PID=$!

agentgateway -f config/agentgateway.yaml &
GATEWAY_PID=$!

# 백엔드와 게이트웨이가 리슨할 시간을 준 뒤 오케스트레이터를 띄운다.
sleep 2

RESEARCH_AGENT_URL="http://127.0.0.1:8001" \
SUMMARIZER_AGENT_URL="http://127.0.0.1:8002" \
python -m orchestrator &
ORCHESTRATOR_PID=$!

cleanup() {
  kill "$RESEARCH_PID" "$SUMMARIZER_PID" "$GATEWAY_PID" "$ORCHESTRATOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "research→:8001, summarizer→:8002 (gateway), orchestrator :9000"
echo "press Ctrl-C to stop"
wait
```

- [ ] **Step 2: bash 문법 검사 + 실행 권한**

Run: `bash -n scripts/run_with_gateway.sh && chmod +x scripts/run_with_gateway.sh && echo ok`
Expected: `ok`
(참고: `agentgateway`의 config 플래그가 `-f`가 아닐 수 있다. Task 6 수동 검증에서 `agentgateway --help`로 실제 플래그를 확인하고, 다르면 이 스크립트의 `-f`를 고친다.)

- [ ] **Step 3: 커밋**

```bash
git add scripts/run_with_gateway.sh
git commit -m "feat: 게이트웨이를 끼운 전체 스택 기동 스크립트 추가"
```

---

### Task 5: README에 게이트웨이 모드 안내 추가

게이트웨이 설치(수동)와 게이트웨이 모드 실행 방법, 환경변수 두 종류의 역할을 README에 문서화한다.

**Files:**
- Modify: `README.md` (실행 섹션 뒤에 게이트웨이 섹션 추가)
- Test: 없음(문서).

**Interfaces:** 없음.

- [ ] **Step 1: README에 섹션 추가**

`README.md`의 "## 테스트" 섹션 **바로 앞에** 아래 섹션을 삽입:

```markdown
## (선택) agentgateway 프록시 모드

[agentgateway](https://agentgateway.dev)를 research/summarizer 앞단에 포트 1:1
프록시로 끼워, 오케스트레이터가 게이트웨이를 통해 에이전트를 호출하게 한다.
게이트웨이 바이너리는 수동 설치한다(설치 안내는 위 링크 참조).

```bash
# 백엔드+게이트웨이+오케스트레이터를 한 번에 기동
./scripts/run_with_gateway.sh
```

매핑: `:8001 → :9001`(research), `:8002 → :9002`(summarizer). 게이트웨이 설정은
`config/agentgateway.yaml`에 있다.

환경변수 두 종류가 각기 다른 프로세스에 주입된다:

- `RESEARCH_PUBLIC_URL` / `SUMMARIZER_PUBLIC_URL` — **백엔드**에 주입. 카드가 광고할
  게이트웨이 주소. 미설정 시 백엔드 직접 주소를 광고한다.
- `RESEARCH_AGENT_URL` / `SUMMARIZER_AGENT_URL` — **오케스트레이터**에 주입. 호출 목적지인
  게이트웨이 주소. 미설정 시 백엔드를 직접 호출한다.

게이트웨이 카드가 게이트웨이 주소를 광고하는지 확인:

```bash
curl -s http://127.0.0.1:8001/.well-known/agent-card.json
```
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: README에 agentgateway 프록시 모드 안내 추가"
```

---

### Task 6: 수동 end-to-end 검증 및 결과 기록

게이트웨이를 끼운 실제 스택을 띄워 spec의 검증 3종을 수행하고, 결과(특히 a2a-sdk 1.1.0 호환성과 SSE 버퍼링 여부)를 기록한다. 이 PoC의 본질적 미지수를 해소하는 단계다.

**Files:**
- 코드 변경 없음. 검증 결과를 spec 문서 하단 또는 메모리에 기록.

**Interfaces:** 없음.

- [ ] **Step 1: 게이트웨이 바이너리 설치 확인**

Run: `command -v agentgateway && agentgateway --help 2>&1 | head -30`
Expected: 바이너리 경로 출력. config 지정 플래그(`-f`/`--file`/`--config`)를 확인하고, Task 4 스크립트의 `-f`와 다르면 스크립트를 수정한다.
(미설치 시: https://agentgateway.dev 설치 안내를 따라 설치한 뒤 진행. 설치 불가하면 이 태스크를 보류로 표시하고 그 사실을 기록한다.)

- [ ] **Step 2: 전체 스택 기동**

Run: `./scripts/run_with_gateway.sh` (별도 터미널에서 실행, 켜둔 채로 다음 스텝 진행)
Expected: research→:8001, summarizer→:8002, orchestrator :9000 기동 로그.

- [ ] **Step 3: 검증 1 — 카드 discovery 통과 + url 광고**

Run: `curl -s http://127.0.0.1:8001/.well-known/agent-card.json | python -c "import sys, json; c = json.load(sys.stdin); print(c['supportedInterfaces'][0]['url'])"`
Expected: `http://127.0.0.1:8001/` (게이트웨이 주소를 광고).
(참고: a2a-sdk가 직렬화하는 카드 JSON의 키 표기가 `supportedInterfaces`/`supported_interfaces`로 다를 수 있다. 실패 시 `curl ... | python -m json.tool`로 실제 키를 확인하고 경로를 맞춘다. `:8002`의 summarizer도 동일하게 확인.)

- [ ] **Step 4: 검증 2 — 오케스트레이터 end-to-end**

Run:
```bash
curl -N -X POST http://127.0.0.1:9000/run \
  -H 'content-type: application/json' \
  -d '{"task":"양자컴퓨팅 최신 동향을 조사해 3문단으로 요약해줘"}'
```
Expected: `data: {...}` SSE 이벤트 스트림. `type`이 `tool_call`/`tool_result`로 research·summarizer 호출이 보이고, 마지막에 `final`이 나온다 — 즉 호출이 게이트웨이를 거쳐 정상 동작.

- [ ] **Step 5: 검증 3 — 스트리밍 중간 이벤트 통과 확인**

Step 4의 스트림에서 서브 에이전트 진행 이벤트(`path`가 붙은 `tool_call`/`tool_result`)가 **점진적으로** 도착하는지 관찰한다.
Expected: 중간 이벤트가 final 이전에 실시간으로 도착. 만약 모든 이벤트가 끝에 한꺼번에 몰려 오거나 중간 이벤트가 0개면, 게이트웨이의 SSE 버퍼링을 의심한다(spec §7 리스크).

- [ ] **Step 6: 결과 기록**

검증 1~3 결과를 spec 문서(`docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md`) 하단에 "## 8. 검증 결과" 섹션으로 추가한다. 최소한 다음을 기록:
- agentgateway가 a2a-sdk 1.1.0 카드 discovery + JSON-RPC message/send를 깨지 않고 중계했는가 (예/아니오 + 증상).
- SSE 중간 이벤트가 게이트웨이를 통과했는가 (예/아니오 + 버퍼링 여부).
- 실제 사용한 agentgateway config 플래그와 버전.

- [ ] **Step 7: 커밋**

```bash
git add docs/superpowers/specs/2026-06-28-agentgateway-a2a-proxy-design.md
git commit -m "docs: agentgateway 프록시 수동 end-to-end 검증 결과 기록"
```
