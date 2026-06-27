"""오케스트레이션 진행을 SSE로 스트리밍하는 일반 HTTP 서버를 구성한다."""
import json
from dataclasses import asdict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from orchestrator.events import ProgressEvent
from orchestrator.orchestrate import run_task_stream


def build_app(run_stream=run_task_stream) -> Starlette:
    """POST /run에서 task를 받아 진행 이벤트를 SSE로 흘리는 앱을 만든다."""
    async def run(request: Request) -> StreamingResponse:
        body = await request.json()
        task = body["task"]

        async def event_stream():
            async for event in run_stream(task):
                yield event_to_sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return Starlette(routes=[Route("/run", run, methods=["POST"])])


def event_to_sse(event: ProgressEvent) -> str:
    """ProgressEvent를 None 필드를 제외한 data: <json> SSE 라인으로 직렬화한다."""
    payload = {key: value for key, value in asdict(event).items() if value is not None}
    return f"data: {json.dumps(payload)}\n\n"
