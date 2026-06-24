from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agents.research.graph import build_research_graph


async def test_research_graph_returns_assistant_text_without_tool_calls():
    # given — 툴 호출 없이 바로 답하는 가짜 모델
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="quantum computing summary")]
    )

    def fake_search(query: str) -> str:
        return "irrelevant"

    graph = build_research_graph(model=fake_model, search_tool=fake_search)

    # when
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "research quantum computing"}]}
    )

    # then
    assert result["messages"][-1].content == "quantum computing summary"
