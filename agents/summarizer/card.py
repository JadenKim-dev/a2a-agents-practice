"""Summarizer 에이전트의 A2A AgentCard를 정의한다."""
from common.agent_card import build_agent_card

SUMMARIZER_URL = "http://127.0.0.1:9002/"

SUMMARIZER_CARD = build_agent_card(
    name="summarizer",
    description="Summarizes provided text into a concise multi-paragraph summary.",
    url=SUMMARIZER_URL,
    skill_id="summarize",
    skill_name="Summarize Text",
    skill_description="Condense provided text into a faithful short summary.",
    skill_tags=["summarize", "text"],
)
