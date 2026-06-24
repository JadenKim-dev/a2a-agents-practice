"""웹 검색으로 주제를 조사하는 Research 에이전트의 LangGraph 그래프 책임."""
from langchain_core.tools import tool
from langchain.agents import create_agent

RESEARCH_SYSTEM_PROMPT = (
    "You are a research assistant. Use the search tool to gather facts about "
    "the user's topic, then write a concise factual briefing."
)


def build_research_graph(model=None, search_tool=None):
    if model is None:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    if search_tool is None:
        from langchain_tavily import TavilySearch
        search_tool = TavilySearch(max_results=3)
        agent_tools = [search_tool]
    elif not hasattr(search_tool, "name"):
        # Plain function injected (e.g., in tests): wrap it but do not bind it
        # to the model because test-only fake models may not implement bind_tools.
        search_tool = tool(search_tool, description="Search the web for information.")
        agent_tools = []
    else:
        agent_tools = [search_tool]
    return create_agent(
        model=model,
        tools=agent_tools,
        system_prompt=RESEARCH_SYSTEM_PROMPT,
    )
