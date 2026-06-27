from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from langchain.agents.middleware import ModelRequest, ModelResponse

from orchestrator.middleware import StepLimitSynthesisMiddleware, SYNTHESIS_PROMPT


def _dummy_tool():
    def run(input: str) -> str:
        return input
    return StructuredTool.from_function(func=run, name="research", description="d")


def _request_with_tools():
    # override가 새 ModelRequest를 dataclasses.replace로 만들므로, 최소 필드만 채운 진짜 ModelRequest를 쓴다.
    return ModelRequest(
        model=None,
        messages=[],
        system_message=None,
        tool_choice=None,
        tools=[_dummy_tool()],
        response_format=None,
        state={"messages": []},
        runtime=None,
        model_settings={},
    )


async def test_keeps_tools_before_limit_is_reached():
    # given — 한도 5, 첫 호출. handler는 받은 request를 기록하고 ModelResponse를 돌려준다.
    middleware = StepLimitSynthesisMiddleware(model_call_limit=5)
    seen = {}

    async def handler(request):
        seen["tools"] = request.tools
        return ModelResponse(result=[AIMessage(content="ok")], structured_response=None)

    # when
    await middleware.awrap_model_call(_request_with_tools(), handler)

    # then
    assert len(seen["tools"]) == 1


async def test_strips_tools_and_injects_synthesis_prompt_on_final_step():
    # given — 한도 1이라 첫 호출이 곧 마지막. handler가 받은 request를 기록.
    middleware = StepLimitSynthesisMiddleware(model_call_limit=1)
    seen = {}

    async def handler(request):
        seen["tools"] = request.tools
        seen["system_prompt"] = request.system_prompt
        return ModelResponse(result=[AIMessage(content="best effort")], structured_response=None)

    # when
    response = await middleware.awrap_model_call(_request_with_tools(), handler)

    # then
    assert seen["tools"] == []
    assert seen["system_prompt"] == SYNTHESIS_PROMPT
    assert response.result[0].response_metadata["truncated"] is True
