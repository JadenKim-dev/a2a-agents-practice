"""
executor와 client 사이의 스트리밍 왕복을 검증하는 통합 테스트.

실제 Starlette 앱을 httpx ASGITransport로 같은 프로세스 안에서 띄워
네트워크 없이 호출한다. 단위 테스트는 이 transport 계층을 monkeypatch로
대체하지만, 여기서는 실제 transport를 그대로 통과시켜 두 가지를 확인한다.

(a) 카드에 streaming=True가 켜져 있으면 SDK가 스트리밍 경로를 타고,
    그 결과 중간 tool_call metadata가 client까지 전달된다.
(b) 중간 이벤트가 여럿 도착해도 마지막에 온 완료 이벤트가 이겨서
    (last-write-wins) 최종 텍스트가 올바르게 남는다.
"""
import httpx
from langchain_core.messages import AIMessage

from a2a.client import A2ACardResolver

from common.agent_card import build_agent_card
from common.langgraph_executor import LangGraphExecutor
from common.server import build_starlette_app
from orchestrator.client import call_agent


BASE_URL = "http://testserver"


class FakeStreamingGraph:
    """astream이 미리 정한 chunk 시퀀스를 순서대로 내는 가짜 LangGraph."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, state, *, stream_mode):
        for chunk in self._chunks:
            yield chunk


def _build_app_with_streaming_card(graph):
    """streaming=True 카드와 주어진 graph로 Starlette 앱을 조립한다."""
    card = build_agent_card(
        name="integration-test-agent",
        description="Integration test agent",
        url=f"{BASE_URL}/",
        skill_id="integration-test",
        skill_name="Integration Test",
        skill_description="Integration test skill",
        skill_tags=["test"],
    )
    executor = LangGraphExecutor(graph)
    return build_starlette_app(card, executor)


async def test_streaming_delivers_tool_call_metadata_and_correct_final_text():
    # given — tool_call chunk 1개 후 최종 텍스트를 내는 graph와 in-process 앱
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "search", "args": {"input": "streaming topic"},
             "id": "c1", "type": "tool_call"},
        ])]}},
        {"model": {"messages": [AIMessage(content="streaming final result")]}},
    ])
    app = _build_app_with_streaming_card(graph)

    # when — ASGITransport으로 in-process 왕복 호출
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as http:
        resolver = A2ACardResolver(http, base_url=BASE_URL)
        card = await resolver.get_agent_card()

        received_metadata: list[dict] = []
        result = await call_agent(
            http, card, "test streaming", on_event=received_metadata.append
        )

    # then — (a) tool_call metadata가 on_event에 최소 1회 도달
    metadatas = [metadata for metadata in received_metadata if metadata.get("kind") == "tool_call"]
    assert len(metadatas) >= 1, (
        f"tool_call metadata가 on_event에 도달하지 않았다. 받은 metadata: {received_metadata}"
    )
    assert metadatas[0]["agent"] == "search"
    assert metadatas[0]["input"] == "streaming topic"

    # then — (b) 최종 텍스트가 graph의 최종 chunk 텍스트와 일치 (last-write-wins 안전)
    assert result == "streaming final result", (
        f"최종 텍스트가 일치하지 않는다: '{result}'"
    )


async def test_resolved_card_has_streaming_enabled():
    # given — build_agent_card로 만든 앱을 기동해 카드를 resolve한다
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="done")]}},
    ])
    app = _build_app_with_streaming_card(graph)

    # when — .well-known 경로로 카드를 resolve한다
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as http:
        resolver = A2ACardResolver(http, base_url=BASE_URL)
        card = await resolver.get_agent_card()

    # then — 카드에 streaming=True가 설정되어 SDK가 streaming 경로를 선택한다
    assert card.capabilities.streaming is True, (
        "card.capabilities.streaming이 False여서 SDK가 non-streaming 경로를 탄다"
    )


async def test_streaming_delivers_multiple_tool_calls_in_order():
    # given — tool_call chunk 2개 후 최종 텍스트를 내는 graph
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "search", "args": {"input": "query A"}, "id": "c1", "type": "tool_call"},
        ])]}},
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "fetch", "args": {"input": "query B"}, "id": "c2", "type": "tool_call"},
        ])]}},
        {"model": {"messages": [AIMessage(content="multi-call final result")]}},
    ])
    app = _build_app_with_streaming_card(graph)

    # when
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as http:
        resolver = A2ACardResolver(http, base_url=BASE_URL)
        card = await resolver.get_agent_card()

        received_metadata: list[dict] = []
        result = await call_agent(
            http, card, "multi-call test", on_event=received_metadata.append
        )

    # then — tool_call 이벤트가 순서대로 2회 도달
    tool_call_events = [m for m in received_metadata if m.get("kind") == "tool_call"]
    assert len(tool_call_events) == 2
    assert tool_call_events[0]["agent"] == "search"
    assert tool_call_events[0]["input"] == "query A"
    assert tool_call_events[1]["agent"] == "fetch"
    assert tool_call_events[1]["input"] == "query B"

    # then — 중간 진행 텍스트가 최종 텍스트를 덮어쓰지 않는다 (last-write-wins)
    assert result == "multi-call final result"


async def test_final_text_last_write_wins_is_safe():
    # given — 중간 status_update가 텍스트를 포함하지만 완료 이벤트가 마지막에 도달하는 graph
    # 이 케이스는 "calling search: ..." 같은 중간 텍스트가 on_event 외부에서
    # final_text를 덮어쓰지 않음을 독립적으로 검증한다.
    graph = FakeStreamingGraph(chunks=[
        {"model": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "search", "args": {"input": "overwrite test"},
             "id": "c1", "type": "tool_call"},
        ])]}},
        {"model": {"messages": [AIMessage(content="CORRECT FINAL TEXT")]}},
    ])
    app = _build_app_with_streaming_card(graph)

    # when
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as http:
        resolver = A2ACardResolver(http, base_url=BASE_URL)
        card = await resolver.get_agent_card()

        result = await call_agent(http, card, "overwrite safety test")

    # then — 중간 "calling search: overwrite test" 텍스트가 아닌 완료 텍스트가 반환된다
    assert result == "CORRECT FINAL TEXT", (
        f"last-write-wins 불안전: 중간 텍스트가 최종을 덮어썼다. 실제 반환값: '{result}'"
    )
    assert "calling" not in result, (
        "중간 진행 요약 텍스트가 최종 반환값을 오염시켰다"
    )
