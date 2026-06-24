"""Research 에이전트의 A2A AgentCard 책임."""
from common.agent_card import build_agent_card

RESEARCH_URL = "http://127.0.0.1:9001/"

RESEARCH_CARD = build_agent_card(
    name="research",
    description="Researches a topic using web search and returns a factual briefing.",
    url=RESEARCH_URL,
    skill_id="research",
    skill_name="Web Research",
    skill_description="Find current information on a topic and summarize the findings.",
    skill_tags=["research", "web-search"],
)
