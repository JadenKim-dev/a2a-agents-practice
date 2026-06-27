"""Summarizer 에이전트 서버 진입점: python -m agents.summarizer → :9002."""
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import run_agent_server
from agents.summarizer.card import SUMMARIZER_CARD
from agents.summarizer.graph import build_summarizer_graph

load_dotenv()


def main() -> None:
    executor = LangGraphExecutor(build_summarizer_graph())
    run_agent_server(SUMMARIZER_CARD, executor, host="127.0.0.1", port=9002)


if __name__ == "__main__":
    main()
