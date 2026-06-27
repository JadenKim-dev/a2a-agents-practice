from langchain_core.messages import AIMessage

from orchestrator.llm import message_content_to_text


def test_returns_string_content_unchanged():
    # given
    message = AIMessage(content="plain text answer")

    # when
    text = message_content_to_text(message)

    # then
    assert text == "plain text answer"


def test_joins_list_of_string_blocks():
    # given
    message = AIMessage(content=["a", "b", "c"])

    # when
    text = message_content_to_text(message)

    # then
    assert text == "abc"


def test_joins_text_blocks_from_dicts():
    # given
    message = AIMessage(content=[
        {"type": "text", "text": "hello "},
        {"type": "text", "text": "world"},
    ])

    # when
    text = message_content_to_text(message)

    # then
    assert text == "hello world"


def test_joins_mixed_string_and_dict_blocks():
    # given
    message = AIMessage(content=[
        "start ",
        {"type": "text", "text": "middle "},
        "end",
    ])

    # when
    text = message_content_to_text(message)

    # then
    assert text == "start middle end"


def test_skips_non_text_blocks():
    # given
    message = AIMessage(content=[
        {"type": "text", "text": "described "},
        {"type": "image_url", "image_url": {"url": "http://example.com/x.png"}},
        {"type": "text", "text": "image"},
    ])

    # when
    text = message_content_to_text(message)

    # then
    assert text == "described image"


def test_treats_text_block_without_text_key_as_empty():
    # given
    message = AIMessage(content=[
        {"type": "text"},
        {"type": "text", "text": "tail"},
    ])

    # when
    text = message_content_to_text(message)

    # then
    assert text == "tail"
