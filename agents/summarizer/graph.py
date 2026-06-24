"""입력 텍스트를 요약하는 Summarizer 에이전트의 LangGraph 그래프 책임."""
from langchain.agents import create_agent

SUMMARIZER_SYSTEM_PROMPT = (
    "You are a summarization assistant. Rewrite the user's text as a clear, "
    "faithful summary of about three paragraphs. Do not add new facts."
)


def build_summarizer_graph(model=None):
    """툴 없이 입력 텍스트를 요약하는 Summarizer 에이전트 그래프를 생성한다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    return create_agent(
        model=model,
        tools=[],
        system_prompt=SUMMARIZER_SYSTEM_PROMPT,
    )
