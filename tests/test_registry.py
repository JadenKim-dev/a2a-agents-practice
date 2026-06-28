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
