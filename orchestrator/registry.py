"""알려진 A2A 에이전트 URL 목록을 두고 카드를 discovery한다."""
import os

import httpx

from a2a.client import A2ACardResolver
from a2a.types import AgentCard

AGENT_URLS: dict[str, str] = {
    "research": os.environ.get("RESEARCH_AGENT_URL", "http://127.0.0.1:9001"),
    "summarizer": os.environ.get("SUMMARIZER_AGENT_URL", "http://127.0.0.1:9002"),
}


async def discover_agents(http: httpx.AsyncClient) -> dict[str, AgentCard]:
    cards: dict[str, AgentCard] = {}
    for name, url in AGENT_URLS.items():
        try:
            resolver = A2ACardResolver(http, base_url=url)
            cards[name] = await resolver.get_agent_card()
        # 한 에이전트의 discovery 실패가 나머지 discovery를 막지 않도록 예외를 잡아 건너뛴다.
        except Exception as error:  # noqa: BLE001
            print(f"[discover] skip {name} ({url}): {error}")
    return cards
