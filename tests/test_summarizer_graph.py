from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agents.summarizer.graph import build_summarizer_graph


async def test_summarizer_graph_returns_summary_text():
    # given
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="short summary in three sentences")]
    )
    graph = build_summarizer_graph(model=fake_model)

    # when
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "long text to summarize ..."}]}
    )

    # then
    assert result["messages"][-1].content == "short summary in three sentences"
