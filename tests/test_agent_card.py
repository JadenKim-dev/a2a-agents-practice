from common.agent_card import build_agent_card


def test_agent_card_url_is_in_supported_interfaces():
    # given
    name = "research"
    url = "http://127.0.0.1:9001/"

    # when
    card = build_agent_card(
        name=name,
        description="Researches topics",
        url=url,
        skill_id="research",
        skill_name="Research",
        skill_description="Find information on a topic",
        skill_tags=["research"],
    )

    # then
    assert card.name == name
    assert len(card.supported_interfaces) == 1
    assert card.supported_interfaces[0].url == url
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.capabilities.streaming == False
    assert card.default_input_modes == ["text"]
    assert card.default_output_modes == ["text"]
    assert len(card.skills) == 1
    assert card.skills[0].id == "research"
    assert card.skills[0].name == "Research"
    assert card.skills[0].description == "Find information on a topic"
    assert list(card.skills[0].tags) == ["research"]
