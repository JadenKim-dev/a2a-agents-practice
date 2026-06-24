"""오케스트레이터 CLI 진입점: python -m orchestrator "<task>"."""
import asyncio
import sys

from dotenv import load_dotenv

from orchestrator.orchestrate import run_task

load_dotenv()


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m orchestrator "<task>"')
        raise SystemExit(1)
    task = sys.argv[1]
    answer = asyncio.run(run_task(task))
    print(answer)


if __name__ == "__main__":
    main()
