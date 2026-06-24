import json

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from common.agent_card import build_agent_card
from orchestrator.planner import plan_calls, cards_to_catalog


def _cards():
    return {
        "research": build_agent_card(
            name="research", description="researches topics",
            url="http://127.0.0.1:9001/", skill_id="research",
            skill_name="Research", skill_description="web research",
            skill_tags=["research"],
        ),
        "summarizer": build_agent_card(
            name="summarizer", description="summarizes text",
            url="http://127.0.0.1:9002/", skill_id="summarize",
            skill_name="Summarize", skill_description="summarize text",
            skill_tags=["summarize"],
        ),
    }


def test_cards_to_catalog_lists_each_agent_name():
    # given
    cards = _cards()

    # when
    catalog = cards_to_catalog(cards)

    # then
    assert "research" in catalog
    assert "summarizer" in catalog


async def test_plan_calls_returns_parsed_plan():
    # given
    plan_json = json.dumps([
        {"agent": "research", "input": "quantum computing trends"},
        {"agent": "summarizer", "input": "{PREVIOUS_OUTPUT}"},
    ])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("research and summarize quantum computing",
                            _cards(), model=fake_model)

    # then
    assert plan == [
        {"agent": "research", "input": "quantum computing trends"},
        {"agent": "summarizer", "input": "{PREVIOUS_OUTPUT}"},
    ]


async def test_plan_calls_filters_unknown_agents():
    # given
    plan_json = json.dumps([
        {"agent": "nonexistent", "input": "x"},
        {"agent": "research", "input": "y"},
    ])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("task", _cards(), model=fake_model)

    # then
    assert plan == [{"agent": "research", "input": "y"}]


async def test_plan_calls_truncates_to_max_calls():
    # given
    plan_json = json.dumps([{"agent": "research", "input": str(i)} for i in range(10)])
    fake_model = FakeMessagesListChatModel(responses=[AIMessage(content=plan_json)])

    # when
    plan = await plan_calls("task", _cards(), model=fake_model, max_calls=3)

    # then
    assert len(plan) == 3


async def test_plan_calls_returns_empty_on_malformed_json():
    # given — LLM이 JSON 배열이 아닌 산문만 반환
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="I'm sorry, I cannot help with that.")]
    )

    # when
    plan = await plan_calls("task", _cards(), model=fake_model)

    # then
    assert plan == []


async def test_plan_calls_returns_empty_on_non_array_json():
    # given — LLM이 배열이 아닌 JSON 객체를 반환
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content='{"agent": "research", "input": "x"}')]
    )

    # when
    plan = await plan_calls("task", _cards(), model=fake_model)

    # then
    assert plan == []
