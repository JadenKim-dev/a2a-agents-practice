"""오케스트레이션 진행을 SSE로 스트리밍하는 일반 HTTP 서버를 구성한다."""
import json
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from orchestrator.events import ProgressEvent
from orchestrator.orchestrate import run_task_stream


class RunRequest(BaseModel):
    """POST /run 요청 body의 형식을 정의한다."""
    task: str


def build_app(run_stream=run_task_stream) -> FastAPI:
    """POST /run에서 task를 받아 진행 이벤트를 SSE로 흘리는 앱을 만든다."""
    app = FastAPI()

    @app.post("/run")
    async def stream_task_events(body: RunRequest) -> EventSourceResponse:
        async def event_stream():
            async for event in run_stream(body.task):
                yield {"data": event_to_payload(event)}

        return EventSourceResponse(event_stream())

    return app


def event_to_payload(event: ProgressEvent) -> str:
    """ProgressEvent를 None 필드를 제외한 JSON 문자열로 직렬화한다."""
    fields = {key: value for key, value in asdict(event).items() if value is not None}
    return json.dumps(fields, ensure_ascii=False)
