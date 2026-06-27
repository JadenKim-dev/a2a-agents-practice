"""원격 A2A 에이전트에 메시지를 보내고 응답 텍스트를 회수한다."""
import httpx

from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, StreamResponse


async def call_agent(http_client: httpx.AsyncClient, card: AgentCard, text: str) -> str:
    client_factory = ClientFactory(ClientConfig(httpx_client=http_client, streaming=False))
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
        extracted_response = extract_response_text(event)
        if extracted_response:
            final_text = extracted_response
    return final_text


def extract_response_text(stream_response: StreamResponse) -> str:
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
