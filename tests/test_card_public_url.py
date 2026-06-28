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
