from orchestrator.orchestrate import execute_plan
from orchestrator.planner import PREVIOUS_OUTPUT_PLACEHOLDER


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
