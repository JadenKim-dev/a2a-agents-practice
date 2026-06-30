"""OTLP 엔드포인트 유무에 따른 setup_telemetry on/off 동작을 검증한다."""
import importlib

import common.telemetry as telemetry


def test_returns_false_and_no_op_when_endpoint_unset(monkeypatch):
    # given
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    module = importlib.reload(telemetry)

    # when
    enabled = module.setup_telemetry("orchestrator")

    # then
    assert enabled is False


def test_returns_true_and_registers_provider_when_endpoint_set(monkeypatch):
    # given
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    module = importlib.reload(telemetry)

    # when
    enabled = module.setup_telemetry("research")

    # then
    from opentelemetry import trace
    assert enabled is True
    assert trace.get_tracer_provider().__class__.__name__ == "TracerProvider"
