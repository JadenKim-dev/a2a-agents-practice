from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agents.research.graph import build_research_graph


class ToolBindingFakeModel(FakeMessagesListChatModel):
    """bind_tools를 지원해 툴 바인딩 경로를 검증할 수 있는 가짜 모델."""

    def bind_tools(self, tools, **kwargs):
        return self


async def test_research_graph_binds_search_tool_and_returns_assistant_text():
    # given — 툴을 바인딩하되 곧바로 답하는 가짜 모델
    fake_model = ToolBindingFakeModel(
        responses=[AIMessage(content="quantum computing summary")]
    )

    def fake_search(query: str) -> str:
        """Search the web for information."""
        return "irrelevant"

    graph = build_research_graph(model=fake_model, search_tool=fake_search)

    # when
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "research quantum computing"}]}
    )

    # then
    assert result["messages"][-1].content == "quantum computing summary"
