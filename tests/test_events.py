# tests/test_events.py
from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.events import (
    ProgressEvent,
    to_progress_event,
    final_event,
    error_event,
)


def test_to_progress_event_maps_tool_call_to_tool_call_event():
    # given — model 노드가 tool_calls를 가진 AIMessage를 낸 chunk
    chunk = {
        "model": {
            "messages": [
                AIMessage(content="", tool_calls=[
                    {"name": "research", "args": {"input": "quantum computing"},
                     "id": "c1", "type": "tool_call"}])
            ]
        }
    }

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "tool_call"
    assert event.agent == "research"
    assert event.input == "quantum computing"


def test_to_progress_event_maps_tool_message_to_tool_result_event():
    # given — tools 노드가 ToolMessage를 낸 chunk
    chunk = {
        "tools": {
            "messages": [
                ToolMessage(content="OUT[quantum computing]", name="research",
                            tool_call_id="c1")
            ]
        }
    }

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "tool_result"
    assert event.agent == "research"
    assert event.output == "OUT[quantum computing]"


def test_to_progress_event_maps_plain_ai_message_to_final_event():
    # given — model 노드가 tool_calls 없는 최종 AIMessage를 낸 chunk
    chunk = {"model": {"messages": [AIMessage(content="final synthesized answer")]}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "final"
    assert event.content == "final synthesized answer"
    assert event.truncated is False


def test_to_progress_event_reads_truncated_marking_from_response_metadata():
    # given — 강제 종합으로 truncated 마킹이 붙은 최종 AIMessage
    message = AIMessage(content="partial best-effort answer")
    message.response_metadata = {"truncated": True}
    chunk = {"model": {"messages": [message]}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event.type == "final"
    assert event.truncated is True


def test_to_progress_event_returns_none_for_unmappable_chunk():
    # given — messages가 비어 매핑할 대상이 없는 chunk
    chunk = {"model": {"messages": []}}

    # when
    event = to_progress_event(chunk)

    # then
    assert event is None
