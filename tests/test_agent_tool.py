from collections.abc import Callable

from common.agent_card import build_agent_card
from orchestrator.agent_tool import build_agent_tool, tool_description


def _research_card():
    return build_agent_card(
        name="research",
        description="Researches a topic using web search.",
        url="http://127.0.0.1:9001/",
        skill_id="research",
        skill_name="Web Research",
        skill_description="Find current information on a topic.",
        skill_tags=["research"],
    )


def test_tool_description_includes_card_description_and_skill_name():
    # given
    card = _research_card()

    # when
    description = tool_description(card)

    # then
    assert "Researches a topic using web search." in description
    assert "Web Research" in description


def test_build_agent_tool_names_tool_after_agent():
    # given
    card = _research_card()

    # when
    tool = build_agent_tool(http=None, name="research", card=card)

    # then
    assert tool.name == "research"
    assert tool.description == tool_description(card)


async def test_build_agent_tool_delegates_input_to_call_agent():
    # given
    card = _research_card()
    received = {}

    async def fake_call_agent(http, card_arg, text, on_event=None):
        received["card"] = card_arg
        received["text"] = text
        return f"briefing-for:{text}"

    tool = build_agent_tool(
        http="HTTP", name="research", card=card, call_agent_fn=fake_call_agent
    )

    # when
    output = await tool.ainvoke({"input": "quantum computing"})

    # then
    assert received["text"] == "quantum computing"
    assert received["card"] is card
    assert output == "briefing-for:quantum computing"


async def test_build_agent_tool_absorbs_call_failure_into_text():
    # given
    card = _research_card()

    async def failing_call_agent(http, card_arg, text, on_event=None):
        raise RuntimeError("connection refused")

    tool = build_agent_tool(
        http=None, name="research", card=card, call_agent_fn=failing_call_agent
    )

    # when
    output = await tool.ainvoke({"input": "x"})

    # then
    assert "connection refused" in output
    assert "research" in output


async def test_build_agent_tool_emits_sub_events_with_path():
    # given — 호출 중 진행 metadata를 콜백하는 가짜 call_agent와 이벤트 싱크
    card = _research_card()
    emitted = []

    async def fake_call_agent(
        http, card_arg, text, on_event: Callable[[dict], None] | None = None
    ):
        assert on_event is not None
        on_event({"kind": "tool_call", "agent": "tavily", "input": "quantum"})
        on_event({"kind": "tool_result", "agent": "tavily", "output": "OUT[quantum]"})
        return "briefing"

    tool = build_agent_tool(
        http="HTTP", name="research", card=card,
        call_agent_fn=fake_call_agent, emit=emitted.append,
    )

    # when
    output = await tool.ainvoke({"input": "quantum"})

    # then — 서브 이벤트가 path=["research"]로 방출되고 최종 텍스트는 반환된다
    assert output == "briefing"
    assert emitted[0].type == "tool_call"
    assert emitted[0].agent == "tavily"
    assert emitted[0].input == "quantum"
    assert emitted[0].path == ["research"]
    assert emitted[1].type == "tool_result"
    assert emitted[1].output == "OUT[quantum]"
    assert emitted[1].path == ["research"]
