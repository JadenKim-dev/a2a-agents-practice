"""알려진 A2A 에이전트 URL 목록과 카드 discovery 책임."""
import httpx

from a2a.client import A2ACardResolver
from a2a.types import AgentCard

AGENT_URLS: dict[str, str] = {
    "research": "http://127.0.0.1:9001",
    "summarizer": "http://127.0.0.1:9002",
}


async def discover_agents(http: httpx.AsyncClient) -> dict[str, AgentCard]:
    cards: dict[str, AgentCard] = {}
    for name, url in AGENT_URLS.items():
        try:
            resolver = A2ACardResolver(http, base_url=url)
            cards[name] = await resolver.get_agent_card()
        except Exception as error:  # noqa: BLE001
            print(f"[discover] skip {name} ({url}): {error}")
    return cards
