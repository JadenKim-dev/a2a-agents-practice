#!/usr/bin/env bash
# 두 에이전트 서버를 백그라운드로 띄우고, 종료 시 정리한다.
set -euo pipefail

python -m agents.research &
RESEARCH_PID=$!
python -m agents.summarizer &
SUMMARIZER_PID=$!

cleanup() {
  kill "$RESEARCH_PID" "$SUMMARIZER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "research (pid $RESEARCH_PID) on :9001, summarizer (pid $SUMMARIZER_PID) on :9002"
echo "press Ctrl-C to stop"
wait
