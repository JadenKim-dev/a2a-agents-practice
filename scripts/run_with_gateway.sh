#!/usr/bin/env bash
# 게이트웨이를 끼운 전체 스택을 띄운다.
#   백엔드는 카드가 게이트웨이 주소를 광고하도록 *_PUBLIC_URL과 함께,
#   오케스트레이터는 게이트웨이를 호출하도록 *_AGENT_URL과 함께 기동한다.
#   agentgateway 바이너리는 PATH에 설치되어 있다고 가정한다.
set -euo pipefail

# 어느 디렉터리에서 실행하든 모듈 경로(python -m ...)와 config 상대경로가 맞도록 repo 루트로 이동한다.
cd "$(dirname "$0")/.."

if ! command -v agentgateway >/dev/null 2>&1; then
  echo "agentgateway 바이너리를 PATH에서 찾을 수 없습니다. https://agentgateway.dev 설치 안내를 참고하세요." >&2
  exit 1
fi

# 관측 모드: OBSERVABILITY=1 이면 OTEL 엔드포인트를 주입해 trace를 켠다(미설정 시 no-op).
OTEL_ENV=""
if [ "${OBSERVABILITY:-0}" = "1" ]; then
  OTEL_ENV="OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317"
  echo "observability ON → OTLP traces to http://localhost:4317 (Jaeger)"
fi

env $OTEL_ENV RESEARCH_PUBLIC_URL="http://127.0.0.1:8080/research/" python -m agents.research &
RESEARCH_PID=$!
env $OTEL_ENV SUMMARIZER_PUBLIC_URL="http://127.0.0.1:8080/summarizer/" python -m agents.summarizer &
SUMMARIZER_PID=$!

agentgateway -f config/agentgateway.yaml &
GATEWAY_PID=$!

# 백엔드와 게이트웨이가 리슨할 시간을 준 뒤 오케스트레이터를 띄운다.
sleep 2

env $OTEL_ENV \
  RESEARCH_AGENT_URL="http://127.0.0.1:8080/research" \
  SUMMARIZER_AGENT_URL="http://127.0.0.1:8080/summarizer" \
  python -m orchestrator &
ORCHESTRATOR_PID=$!

cleanup() {
  kill "$RESEARCH_PID" "$SUMMARIZER_PID" "$GATEWAY_PID" "$ORCHESTRATOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "research→:8080/research, summarizer→:8080/summarizer (gateway), orchestrator :9000"
echo "press Ctrl-C to stop"
wait
