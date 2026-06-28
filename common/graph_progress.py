"""LangGraph astream chunk를 프레임워크 중립 진행 정보로 추출하고 표현 형태로 변환한다."""
from dataclasses import dataclass

from langchain_core.messages import AIMessage, ToolMessage

from orchestrator.llm import message_content_to_text


@dataclass
class GraphStep:
    """LangGraph 한 스텝의 진행 정보를 프레임워크 중립적으로 표현한다."""
    kind: str
    agent: str | None = None
    input: str | None = None
    output: str | None = None
    content: str | None = None
    truncated: bool = False


def extract_graph_step(chunk: dict) -> GraphStep | None:
    """astream updates chunk 하나에서 첫 매핑 가능한 메시지를 GraphStep으로 추출한다. 없으면 None을 반환한다."""
    for update in chunk.values():
        for message in update.get("messages", []):
            step = _message_to_step(message)
            if step is not None:
                return step
    return None


def _message_to_step(message) -> GraphStep | None:
    if isinstance(message, AIMessage) and message.tool_calls:
        call = message.tool_calls[0]
        return GraphStep(kind="tool_call", agent=call["name"], input=call["args"].get("input", ""))
    if isinstance(message, ToolMessage):
        return GraphStep(kind="tool_result", agent=message.name or "unknown",
                         output=message_content_to_text(message))
    if isinstance(message, AIMessage):
        truncated = bool(message.response_metadata.get("truncated", False))
        return GraphStep(kind="final", content=message_content_to_text(message), truncated=truncated)
    return None


def step_metadata(step: GraphStep) -> dict:
    """GraphStep을 status_update에 실을 구조화 metadata dict로 변환한다."""
    if step.kind == "tool_call":
        return {"kind": "tool_call", "agent": step.agent or "", "input": step.input or ""}
    return {"kind": "tool_result", "agent": step.agent or "", "output": step.output or ""}


def step_summary(step: GraphStep) -> str:
    """GraphStep을 사람이 읽을 한 줄 요약 텍스트로 만든다."""
    if step.kind == "tool_call":
        return f"calling {step.agent}: {step.input or ''}"
    return f"{step.agent} returned: {step.output or ''}"
