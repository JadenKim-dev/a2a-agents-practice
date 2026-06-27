from langchain_core.messages import AIMessage, ToolMessage

from common.graph_progress import extract_graph_step


def test_extract_graph_step_maps_tool_call():
    # given — tool_calls를 가진 AIMessage chunk
    chunk = {"model": {"messages": [
        AIMessage(content="", tool_calls=[
            {"name": "tavily", "args": {"input": "quantum"}, "id": "c1", "type": "tool_call"}])]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "tool_call"
    assert step.agent == "tavily"
    assert step.input == "quantum"


def test_extract_graph_step_maps_tool_result():
    # given — ToolMessage chunk
    chunk = {"tools": {"messages": [
        ToolMessage(content="OUT[quantum]", name="tavily", tool_call_id="c1")]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "tool_result"
    assert step.agent == "tavily"
    assert step.output == "OUT[quantum]"


def test_extract_graph_step_maps_final_message():
    # given — tool_calls 없는 최종 AIMessage chunk
    chunk = {"model": {"messages": [AIMessage(content="final answer")]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "final"
    assert step.content == "final answer"
    assert step.truncated is False


def test_extract_graph_step_reads_truncated_from_response_metadata():
    # given — truncated 마킹이 붙은 최종 AIMessage chunk
    message = AIMessage(content="partial")
    message.response_metadata = {"truncated": True}
    chunk = {"model": {"messages": [message]}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is not None
    assert step.kind == "final"
    assert step.truncated is True


def test_extract_graph_step_returns_none_for_empty_chunk():
    # given — 매핑 대상이 없는 chunk
    chunk = {"model": {"messages": []}}

    # when
    step = extract_graph_step(chunk)

    # then
    assert step is None
