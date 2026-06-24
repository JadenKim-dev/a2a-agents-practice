"""Research 에이전트 서버 진입점: python -m agents.research → :9001."""
from dotenv import load_dotenv

from common.langgraph_executor import LangGraphExecutor
from common.server import run_agent_server
from agents.research.card import RESEARCH_CARD
from agents.research.graph import build_research_graph

load_dotenv()


def main() -> None:
    executor = LangGraphExecutor(build_research_graph())
    run_agent_server(RESEARCH_CARD, executor, host="127.0.0.1", port=9001)


if __name__ == "__main__":
    main()
