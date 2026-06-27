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

    async def fake_call_agent(http, card_arg, text):
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

    async def failing_call_agent(http, card_arg, text):
        raise RuntimeError("connection refused")

    tool = build_agent_tool(
        http=None, name="research", card=card, call_agent_fn=failing_call_agent
    )

    # when
    output = await tool.ainvoke({"input": "x"})

    # then
    assert "connection refused" in output
    assert "research" in output
