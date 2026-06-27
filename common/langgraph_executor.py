"""LangGraph 그래프를 A2A AgentExecutor로 변환하는 어댑터다."""
from collections.abc import AsyncIterator
from typing import Protocol

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.types import Part, TaskState

from common.graph_progress import GraphStep, extract_graph_step


class InvocableGraph(Protocol):
    """LangGraphExecutor가 그래프에 요구하는 최소 스트리밍 규약"""

    def astream(self, state: dict, *, stream_mode: str) -> AsyncIterator[dict]: ...


class LangGraphExecutor(AgentExecutor):
    """주입된 LangGraph 그래프를 스트리밍 실행해 중간 진행과 최종 결과를 A2A로 발행한다."""

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
        final_text = ""
        try:
            async for chunk in self._graph.astream(
                {"messages": [{"role": "user", "content": user_text}]},
                stream_mode="updates",
            ):
                step = extract_graph_step(chunk)
                if step is None:
                    continue
                if step.kind == "final":
                    final_text = step.content or ""
                    continue
                await self._emit_step(updater, step)
        except Exception as error:  # noqa: BLE001 — 서버 무중단 보장
            await updater.failed(
                message=updater.new_agent_message(parts=[Part(text=f"agent error: {error}")])
            )
            return
        await updater.complete(
            message=updater.new_agent_message(parts=[Part(text=final_text)])
        )

    async def _emit_step(self, updater: TaskUpdater, step: GraphStep) -> None:
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=updater.new_agent_message(
                parts=[Part(text=step_summary(step))],
                metadata=step_metadata(step),
            ),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is out of scope for the PoC")


def step_metadata(step: GraphStep) -> dict:
    """GraphStep을 status_update에 실을 구조화 metadata dict로 변환한다."""
    if step.kind == "tool_call":
        return {"kind": "tool_call", "agent": step.agent or "", "input": step.input or ""}
    return {"kind": "tool_result", "agent": step.agent or "", "output": step.output or ""}


def step_summary(step: GraphStep) -> str:
    """GraphStep을 사람이 읽을 한 줄 요약 텍스트로 만든다."""
    if step.kind == "tool_call":
        return f"calling {step.agent}: {step.input or ''}"
    return f"{step.agent} returned: {step.output or ''}"
