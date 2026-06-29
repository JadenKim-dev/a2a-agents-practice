"""오케스트레이터 서버 진입점: python -m orchestrator → :9000 SSE 서버."""
import uvicorn
from dotenv import load_dotenv

from common.telemetry import setup_telemetry
from orchestrator.server import build_app

load_dotenv()


def main() -> None:
    enabled = setup_telemetry("orchestrator")
    app = build_app()
    if enabled:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    uvicorn.run(app, host="127.0.0.1", port=9000)


if __name__ == "__main__":
    main()
