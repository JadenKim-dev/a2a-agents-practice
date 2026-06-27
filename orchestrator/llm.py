"""LangChain 메시지 응답을 일반 문자열로 정규화한다."""
from langchain_core.messages import BaseMessage


def message_content_to_text(message: BaseMessage) -> str:
    """LangChain 메시지의 content를 일반 문자열로 평탄화한다.

    메시지 content는 문자열일 수도, content 블록(텍스트 또는 dict)의 리스트일 수도 있다.
    모든 텍스트 조각을 모아 하나의 문자열로 이어붙인다.
    """
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)
