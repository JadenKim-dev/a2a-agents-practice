"""step limit 도달 직전에 도구를 제거하고 종합을 강제해 best-effort 답변을 만든다."""
from langchain.agents.middleware import AgentMiddleware

SYNTHESIS_PROMPT = (
    "You have reached the step budget and may not call any more tools. "
    "Using only the information gathered so far, write the best possible "
    "final answer to the user's task. Acknowledge briefly if it is incomplete."
)


class StepLimitSynthesisMiddleware(AgentMiddleware):
    """모델 호출이 한도에 도달하는 스텝에서 도구를 비우고 종합을 강제한다."""

    def __init__(self, model_call_limit: int):
        super().__init__()
        self._model_call_limit = model_call_limit
        self._call_count = 0

    async def awrap_model_call(self, request, handler):
        self._call_count += 1
        if self._call_count >= self._model_call_limit:
            request = request.override(tools=[], system_prompt=SYNTHESIS_PROMPT)
            response = await handler(request)
            message = response.result[0]
            message.response_metadata = {**message.response_metadata, "truncated": True}
            return response
        return await handler(request)
