import json

from starlette.testclient import TestClient

from orchestrator.events import tool_call_event, final_event
from orchestrator.server import build_app, event_to_sse


def test_event_to_sse_serializes_only_present_fields():
    # given — agent와 input만 있는 tool_call 이벤트
    event = tool_call_event(agent="research", input="quantum")

    # when
    line = event_to_sse(event)

    # then
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    payload = json.loads(line[len("data: "):].strip())
    assert payload == {"type": "tool_call", "agent": "research", "input": "quantum"}


def test_post_run_streams_events_as_sse():
    # given — 두 이벤트를 내는 fake run_stream을 주입한 앱
    async def fake_run_stream(task, **kwargs):
        yield tool_call_event(agent="research", input=task)
        yield final_event(content="done", truncated=False)

    client = TestClient(build_app(run_stream=fake_run_stream))

    # when
    response = client.post("/run", json={"task": "hello"})

    # then
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = [b for b in response.text.split("\n\n") if b]
    first = json.loads(blocks[0][len("data: "):])
    last = json.loads(blocks[1][len("data: "):])
    assert first == {"type": "tool_call", "agent": "research", "input": "hello"}
    assert last == {"type": "final", "content": "done", "truncated": False}
