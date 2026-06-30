"""Research 에이전트 서버 진입점: python -m agents.research → :9001."""
import uvicorn
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import build_starlette_app
from common.telemetry import setup_telemetry
from agents.research.card import RESEARCH_CARD
from agents.research.graph import build_research_graph

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("research")
    executor = LangGraphExecutor(build_research_graph())
    app = build_starlette_app(RESEARCH_CARD, executor)
    if enabled:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
        StarletteInstrumentor().instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9001)


if __name__ == "__main__":
    main()
