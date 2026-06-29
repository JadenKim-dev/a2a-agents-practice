"""Summarizer 에이전트 서버 진입점: python -m agents.summarizer → :9002."""
import uvicorn
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import build_starlette_app
from common.telemetry import setup_telemetry
from agents.summarizer.card import SUMMARIZER_CARD
from agents.summarizer.graph import build_summarizer_graph

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("summarizer")
    executor = LangGraphExecutor(build_summarizer_graph())
    app = build_starlette_app(SUMMARIZER_CARD, executor)
    if enabled:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
        StarletteInstrumentor().instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9002)


if __name__ == "__main__":
    main()
