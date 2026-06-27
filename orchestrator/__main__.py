"""오케스트레이터 서버 진입점: python -m orchestrator → :9000 SSE 서버."""
import uvicorn
from dotenv import load_dotenv

from orchestrator.server import build_app

load_dotenv()


def main() -> None:
    uvicorn.run(build_app(), host="127.0.0.1", port=9000)


if __name__ == "__main__":
    main()
