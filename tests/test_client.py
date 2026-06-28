from a2a.types import (
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from orchestrator.client import extract_progress_metadata, extract_response_text


def _status_update_response(text, metadata):
    msg = Message(message_id="a1", role=Role.ROLE_AGENT, parts=[Part(text=text)], metadata=metadata)
    status = TaskStatus(state=TaskState.TASK_STATE_WORKING, message=msg)
    return StreamResponse(status_update=TaskStatusUpdateEvent(task_id="t1", context_id="c1", status=status))


def test_extract_progress_metadata_returns_dict_when_kind_present():
    # given — kind를 가진 status_update
    response = _status_update_response(
        "calling tavily", {"kind": "tool_call", "agent": "tavily", "input": "quantum"})

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata == {"kind": "tool_call", "agent": "tavily", "input": "quantum"}


def test_extract_progress_metadata_returns_none_when_no_metadata():
    # given — metadata 없는 status_update (표준 텍스트만)
    response = _status_update_response("plain progress text", None)

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata is None


def test_extract_progress_metadata_returns_none_for_completed_task():
    # given — 완료 Task payload (status_update 아님)
    msg = Message(message_id="a1", role=Role.ROLE_AGENT, parts=[Part(text="final")])
    task = Task(id="t1", context_id="c1",
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=msg))
    response = StreamResponse(task=task)

    # when
    metadata = extract_progress_metadata(response)

    # then
    assert metadata is None
