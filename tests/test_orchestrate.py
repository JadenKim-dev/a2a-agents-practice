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
from orchestrator.orchestrate import execute_plan
from orchestrator.planner import PREVIOUS_OUTPUT_PLACEHOLDER


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


async def test_execute_plan_chains_previous_output():
    # given — 두 단계: research 출력이 summarizer 입력으로 치환되어야 함
    cards = {"research": object(), "summarizer": object()}
    plan = [
        {"agent": "research", "input": "quantum computing"},
        {"agent": "summarizer", "input": PREVIOUS_OUTPUT_PLACEHOLDER},
    ]
    calls = []

    async def fake_call_agent(http, card, text):
        calls.append(text)
        return f"output-for:{text}"

    # when
    steps = await execute_plan(
        http=None, cards=cards, plan=plan, call_agent_fn=fake_call_agent
    )

    # then
    assert calls[0] == "quantum computing"
    assert calls[1] == "output-for:quantum computing"  # placeholder 치환됨
    assert steps[1]["output"] == "output-for:output-for:quantum computing"


async def test_execute_plan_records_error_on_failure():
    # given
    cards = {"research": object()}
    plan = [{"agent": "research", "input": "x"}]

    async def failing_call_agent(http, card, text):
        raise RuntimeError("connection refused")

    # when
    steps = await execute_plan(
        http=None, cards=cards, plan=plan, call_agent_fn=failing_call_agent
    )

    # then
    assert "connection refused" in steps[0]["output"]
