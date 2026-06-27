"""웹 검색으로 주제를 조사하는 Research 에이전트의 LangGraph 그래프를 정의한다."""
from langchain_core.tools import tool
from langchain.agents import create_agent

RESEARCH_SYSTEM_PROMPT = (
    "You are a research assistant. Use the search tool to gather facts about "
    "the user's topic, then write a concise factual briefing."
)


def build_research_graph(model=None, search_tool=None):
    """웹 검색 툴을 바인딩한 Research 에이전트 그래프를 생성한다."""
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    if search_tool is None:
        from langchain_tavily import TavilySearch
        search_tool = TavilySearch(max_results=3)
    elif not hasattr(search_tool, "name"):
        search_tool = tool(search_tool)
    return create_agent(
        model=model,
        tools=[search_tool],
        system_prompt=RESEARCH_SYSTEM_PROMPT,
    )
