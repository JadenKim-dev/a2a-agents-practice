"""LangChain 메시지 응답을 일반 문자열로 정규화하는 책임."""
from langchain_core.messages import BaseMessage


def message_content_to_text(message: BaseMessage) -> str:
    """Responsible for flattening a LangChain message's content into a plain string.

    Message content may be a string or a list of content blocks (text or dict);
    this collects every text fragment and joins them into a single string.
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
