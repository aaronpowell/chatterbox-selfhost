import logging
import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import grpc
import pytest
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app import observability
from app.observability import (
    _GRPC_OTLP_PROTOCOL, _HTTP_OTLP_PROTOCOL, _build_exporter_endpoint,
    _normalize_signal_endpoint, _resolve_otlp_protocol,
)


def test_resolve_otlp_protocol_prefers_explicit_value():
    assert _resolve_otlp_protocol("grpc", "https://localhost:21293", None) == _GRPC_OTLP_PROTOCOL
    assert _resolve_otlp_protocol("http/protobuf", "https://localhost:21293", None) == _HTTP_OTLP_PROTOCOL


def test_seq_uses_http_when_no_otlp_endpoint():
    assert _resolve_otlp_protocol("grpc", None, "http://localhost:5341") == _HTTP_OTLP_PROTOCOL
    assert _build_exporter_endpoint(None, "http://localhost:5341/") == "http://localhost:5341/ingest/otlp"
    assert _build_exporter_endpoint("https://localhost:21293", "http://localhost:5341") == "https://localhost:21293"


def test_invalid_protocol_is_not_silently_replaced():
    with pytest.raises(ValueError, match="Unsupported OTLP protocol"):
        _resolve_otlp_protocol("invalid", "https://localhost:21293", None)


def test_normalize_signal_endpoint_for_http_adds_missing_signal_path():
    assert (
        _normalize_signal_endpoint(
            endpoint="http://localhost:4318",
            signal="logs",
            protocol=_HTTP_OTLP_PROTOCOL,
        )
        == "http://localhost:4318/v1/logs"
    )


def test_normalize_signal_endpoint_for_grpc_strips_paths():
    assert (
        _normalize_signal_endpoint(
            endpoint="https://localhost:21293/v1/traces",
            signal="traces",
            protocol=_GRPC_OTLP_PROTOCOL,
        )
        == "https://localhost:21293"
    )


@pytest.mark.parametrize(
    ("endpoint", "signal", "expected"),
    [
        ("http://collector/prefix", "traces", "http://collector/prefix/v1/traces"),
        ("http://collector/v1/traces", "logs", "http://collector/v1/logs"),
        ("http://seq/ingest/otlp", "logs", "http://seq/ingest/otlp/v1/logs"),
        ("http://seq/ingest/otlp/v1/traces", "logs", "http://seq/ingest/otlp/v1/logs"),
        ("http://collector/v1/traces", "traces", "http://collector/v1/traces"),
    ],
)
def test_http_signal_paths(endpoint, signal, expected):
    assert _normalize_signal_endpoint(endpoint=endpoint, signal=signal, protocol=_HTTP_OTLP_PROTOCOL) == expected


@pytest.mark.parametrize("signal", ["traces", "logs"])
@pytest.mark.parametrize("protocol", ["grpc", "http/protobuf"])
def test_exporter_selection_honors_signal_specific_environment(monkeypatch, signal, protocol):
    monkeypatch.setenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_PROTOCOL", protocol)
    monkeypatch.setenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT", "http://specific:4317/custom")
    module = "grpc" if protocol == "grpc" else "http"
    exporter_name = "OTLPSpanExporter" if signal == "traces" else "OTLPLogExporter"
    exporter_module = "trace_exporter" if signal == "traces" else "_log_exporter"
    factory = observability._create_span_exporter if signal == "traces" else observability._create_log_exporter
    with patch(f"opentelemetry.exporter.otlp.proto.{module}.{exporter_module}.{exporter_name}") as exporter:
        factory(endpoint="http://general:4317", protocol="grpc")
    exporter.assert_called_once_with(endpoint="http://specific:4317/custom")


def test_configuration_preserves_aspire_resource_identity(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "api")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.instance.id=api-instance,custom.tag=test")
    monkeypatch.setattr(observability, "_tracing_configured", False)
    with (
        patch.object(observability, "TracerProvider") as provider_cls,
        patch.object(observability.trace, "set_tracer_provider"),
        patch.object(observability.atexit, "register"),
    ):
        observability.configure_tracing(
            service_name="fallback-api", environment="test", enable_tracing=False,
            otlp_endpoint=None, otlp_protocol="grpc",
        )
    attributes = provider_cls.call_args.kwargs["resource"].attributes
    assert attributes["service.name"] == "api"
    assert attributes["service.instance.id"] == "api-instance"
    assert attributes["custom.tag"] == "test"


def test_log_export_includes_named_loggers_context_and_exceptions():
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    tracer_provider = TracerProvider()
    loggers = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "rq.worker")]
    original_handlers = [list(logger.handlers) for logger in loggers]
    original_levels = [logger.level for logger in loggers]
    try:
        observability._attach_log_handler(provider)
        for logger in loggers:
            logger.setLevel(logging.INFO)
        with observability.request_context("diagnostic-request"), tracer_provider.get_tracer(__name__).start_as_current_span("test") as span:
            for name in ("app.request", "uvicorn.error", "rq.worker"):
                logging.getLogger(name).info("diagnostic %s", name)
            try:
                raise ValueError("test exception")
            except ValueError:
                logging.getLogger("app.request").exception("synthesis failed")
            logging.getLogger("opentelemetry.exporter").error("export failed")
        records = [item.log_record for item in exporter.get_finished_logs()]
        assert len(records) == 4
        assert all(record.trace_id == span.get_span_context().trace_id for record in records)
        assert all(record.attributes["request_id"] == "diagnostic-request" for record in records)
        assert records[-1].attributes["exception.type"] == "ValueError"
        assert "test exception" in records[-1].attributes["exception.stacktrace"]
    finally:
        for logger, handlers, level in zip(loggers, original_handlers, original_levels):
            logger.handlers = handlers
            logger.setLevel(level)
        provider.shutdown()
        tracer_provider.shutdown()


@pytest.mark.parametrize("protocol", ["grpc", "http/protobuf"])
def test_real_otlp_export_delivers_correlated_logs_and_traces(monkeypatch, protocol):
    for key in list(os.environ):
        if key.startswith("OTEL_EXPORTER_OTLP"):
            monkeypatch.delenv(key)
    received = {}
    if protocol == "grpc":
        class TraceReceiver(trace_service_pb2_grpc.TraceServiceServicer):
            def Export(self, request, context):
                received["traces"] = request
                return trace_service_pb2.ExportTraceServiceResponse()

        class LogReceiver(logs_service_pb2_grpc.LogsServiceServicer):
            def Export(self, request, context):
                received["logs"] = request
                return logs_service_pb2.ExportLogsServiceResponse()

        executor = ThreadPoolExecutor(max_workers=2)
        server = grpc.server(executor)
        trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceReceiver(), server)
        logs_service_pb2_grpc.add_LogsServiceServicer_to_server(LogReceiver(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
    else:
        class HttpReceiver(BaseHTTPRequestHandler):
            def do_POST(self):
                signal = self.path.rsplit("/", 1)[-1]
                message = (trace_service_pb2.ExportTraceServiceRequest() if signal == "traces"
                           else logs_service_pb2.ExportLogsServiceRequest())
                message.ParseFromString(self.rfile.read(int(self.headers["Content-Length"])))
                received[signal] = message
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), HttpReceiver)
        port = server.server_port
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

    endpoint = f"http://127.0.0.1:{port}"
    tracer_provider = TracerProvider()
    logger_provider = LoggerProvider()
    try:
        tracer_provider.add_span_processor(SimpleSpanProcessor(
            observability._create_span_exporter(endpoint=endpoint, protocol=protocol),
        ))
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(
            observability._create_log_exporter(endpoint=endpoint, protocol=protocol),
        ))
        handler = LoggingHandler(logger_provider=logger_provider)
        with tracer_provider.get_tracer(__name__).start_as_current_span("export-test"):
            handler.handle(logging.LogRecord("test", logging.INFO, __file__, 0, "test log", (), None))
        trace = received["traces"].resource_spans[0].scope_spans[0].spans[0]
        log = received["logs"].resource_logs[0].scope_logs[0].log_records[0]
        assert trace.name == "export-test"
        assert log.body.string_value == "test log"
        assert log.trace_id == trace.trace_id
        assert log.span_id == trace.span_id
    finally:
        tracer_provider.shutdown()
        logger_provider.shutdown()
        if protocol == "grpc":
            server.stop(0).wait()
            executor.shutdown()
        else:
            server.shutdown()
            server.server_close()
            thread.join()
