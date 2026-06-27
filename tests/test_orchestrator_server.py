import json

from fastapi.testclient import TestClient

from orchestrator.events import tool_call_event, final_event
from orchestrator.server import build_app, event_to_payload


def test_event_to_payload_serializes_only_present_fields():
    # given — agent와 input만 있는 tool_call 이벤트
    event = tool_call_event(agent="research", input="quantum")

    # when
    payload = json.loads(event_to_payload(event))

    # then
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
    payloads = [json.loads(block[len("data: "):])
                for block in response.text.split("\r\n\r\n") if block]
    assert payloads[0] == {"type": "tool_call", "agent": "research", "input": "hello"}
    assert payloads[1] == {"type": "final", "content": "done", "truncated": False}
