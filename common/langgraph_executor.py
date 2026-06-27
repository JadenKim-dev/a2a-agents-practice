"""LangGraph 그래프를 A2A AgentExecutor로 변환하는 어댑터다."""
from typing import Any, Protocol

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.types import Part


class InvocableGraph(Protocol):
    """LangGraphExecutor가 그래프에 요구하는 최소 호출 규약"""

    async def ainvoke(self, state: dict) -> dict[str, Any]: ...


class LangGraphExecutor(AgentExecutor):
    """주입된 LangGraph 그래프 하나를 실행해 A2A Task로 응답한다."""

    def __init__(self, graph: InvocableGraph):
        self._graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            if context.message is None:
                raise ValueError("request has neither a current task nor a user message")
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        user_text = context.get_user_input()
        try:
            result = await self._graph.ainvoke(
                {"messages": [{"role": "user", "content": user_text}]}
            )
        except Exception as error:  # noqa: BLE001 — 서버 무중단 보장
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[Part(text=f"agent error: {error}")]
                )
            )
            return
        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=extract_last_text(result))]
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is out of scope for the PoC")


def extract_last_text(graph_result: dict) -> str:
    messages = graph_result.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", last)
    return content if isinstance(content, str) else str(content)
