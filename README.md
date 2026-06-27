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
