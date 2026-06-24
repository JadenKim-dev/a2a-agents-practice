from a2a.types import (
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskStatus,
    TaskState,
)

from orchestrator.client import extract_response_text


def test_extract_response_text_reads_task_status_message():
    # given — 서버가 보내는 완료 Task를 흉내
    agent_msg = Message(
        message_id="a1",
        role=Role.ROLE_AGENT,
        parts=[Part(text="final answer")],
    )
    task = Task(
        id="t1",
        context_id="c1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=agent_msg),
    )
    response = StreamResponse(task=task)

    # when
    text = extract_response_text(response)

    # then
    assert text == "final answer"
