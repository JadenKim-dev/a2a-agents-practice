"""AgentCard와 Executor로 A2A Starlette 앱을 조립하고 uvicorn으로 기동하는 책임."""
import uvicorn
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard


def build_starlette_app(card: AgentCard, executor: AgentExecutor) -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(
        handler, rpc_url="/"
    )
    return Starlette(routes=routes)


def run_agent_server(
    card: AgentCard, executor: AgentExecutor, host: str, port: int
) -> None:
    uvicorn.run(build_starlette_app(card, executor), host=host, port=port)
