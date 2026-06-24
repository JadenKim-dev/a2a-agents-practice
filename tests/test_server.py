from starlette.applications import Starlette

from common.agent_card import build_agent_card
from common.langgraph_executor import LangGraphExecutor


class FakeGraph:
    async def ainvoke(self, state):
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="ok")]}


def test_build_starlette_app_exposes_agent_card_route():
    # given
    card = build_agent_card(
        name="research",
        description="d",
        url="http://127.0.0.1:9001/",
        skill_id="research",
        skill_name="Research",
        skill_description="d",
        skill_tags=["research"],
    )
    executor = LangGraphExecutor(FakeGraph())

    # when
    from common.server import build_starlette_app
    app = build_starlette_app(card, executor)

    # then
    assert isinstance(app, Starlette)
    paths = {r.path for r in app.routes}
    assert "/.well-known/agent-card.json" in paths
