"""원격 A2A 에이전트에 메시지를 보내고 진행 콜백과 최종 응답 텍스트를 회수한다."""
from collections.abc import Callable

import httpx

from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, StreamResponse


async def call_agent(
    http_client: httpx.AsyncClient,
    card: AgentCard,
    text: str,
    on_event: Callable[[dict], None] | None = None,
) -> str:
    """원격 에이전트를 스트리밍 호출하며 진행 metadata를 on_event로 흘리고 최종 텍스트를 반환한다."""
    client_factory = ClientFactory(ClientConfig(httpx_client=http_client, streaming=True))
    client = client_factory.create(card)
    request = SendMessageRequest(
        message=Message(
            message_id="orchestrator-msg",
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )
    )
    final_text = ""
    async for event in client.send_message(request):
        if on_event is not None:
            metadata = extract_progress_metadata(event)
            if metadata is not None:
                on_event(metadata)
        extracted_response = extract_response_text(event)
        if extracted_response:
            final_text = extracted_response
    return final_text


def extract_progress_metadata(stream_response: StreamResponse) -> dict | None:
    """status_update의 message.metadata에서 진행 정보 dict를 꺼낸다. kind가 없으면 None을 반환한다."""
    if stream_response.WhichOneof("payload") != "status_update":
        return None
    message = stream_response.status_update.status.message
    if not message:
        return None
    metadata = dict(message.metadata)
    if "kind" not in metadata:
        return None
    return metadata


def extract_response_text(stream_response: StreamResponse) -> str:
    """완료 payload에서 최종 응답 텍스트를 꺼낸다. 없으면 빈 문자열을 반환한다."""
    payload_kind = stream_response.WhichOneof("payload")
    if payload_kind == "task":
        status = stream_response.task.status
        if status.message and status.message.parts:
            return status.message.parts[0].text
    if payload_kind == "message":
        parts = stream_response.message.parts
        if parts:
            return parts[0].text
    if payload_kind == "status_update":
        message = stream_response.status_update.status.message
        if message and message.parts:
            return message.parts[0].text
    return ""
