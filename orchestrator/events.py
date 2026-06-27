"""ReAct 스트림 chunk를 사용자에게 노출할 진행 이벤트로 변환한다."""
from dataclasses import dataclass

from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.llm import message_content_to_text


@dataclass
class ProgressEvent:
    """오케스트레이션 진행의 한 스텝을 표현한다."""
    type: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool | None = None
    message: str | None = None
    path: list[str] | None = None


def to_progress_event(chunk: dict) -> ProgressEvent | None:
    """astream updates chunk 하나를 진행 이벤트로 변환한다. 매핑 대상이 없으면 None을 반환한다."""
    for update in chunk.values():
        for message in update.get("messages", []):
            event = _message_to_event(message)
            if event is not None:
                return event
    return None


def tool_call_event(agent: str, input: str) -> ProgressEvent:
    """LLM이 에이전트 tool 호출을 결정한 스텝 이벤트를 만든다."""
    return ProgressEvent(type="tool_call", agent=agent, input=input)


def tool_result_event(agent: str, output: str) -> ProgressEvent:
    """원격 에이전트 호출 결과를 관찰한 스텝 이벤트를 만든다."""
    return ProgressEvent(type="tool_result", agent=agent, output=output)


def final_event(content: str, truncated: bool) -> ProgressEvent:
    """ReAct 종료(또는 강제 종합)의 최종 답변 이벤트를 만든다."""
    return ProgressEvent(type="final", content=content, truncated=truncated)


def error_event(message: str) -> ProgressEvent:
    """스트림 도중 발생한 예외를 알리는 이벤트를 만든다."""
    return ProgressEvent(type="error", message=message)


def _message_to_event(message) -> ProgressEvent | None:
    if isinstance(message, AIMessage) and message.tool_calls:
        call = message.tool_calls[0]
        return tool_call_event(agent=call["name"], input=call["args"].get("input", ""))
    if isinstance(message, ToolMessage):
        return tool_result_event(agent=message.name or "unknown", output=message_content_to_text(message))
    if isinstance(message, AIMessage):
        truncated = bool(message.response_metadata.get("truncated", False))
        return final_event(content=message_content_to_text(message), truncated=truncated)
    return None
