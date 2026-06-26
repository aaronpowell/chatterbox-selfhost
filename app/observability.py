import atexit
import logging
import logging.config
import os
import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token

from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_logging_configured = False
_tracing_configured = False
_fastapi_instrumented = False
_sqlalchemy_instrumented = False


class ObservabilityContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get() or "-"

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            record.trace_id = f"{span_context.trace_id:032x}"
            record.span_id = f"{span_context.span_id:016x}"
        else:
            record.trace_id = "-"
            record.span_id = "-"

        return True


def configure_logging(log_level: str) -> None:
    global _logging_configured
    if _logging_configured:
        return

    resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "observability": {
                    "()": "app.observability.ObservabilityContextFilter",
                }
            },
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s %(levelname)s [%(name)s] "
                        "[request_id=%(request_id)s trace_id=%(trace_id)s span_id=%(span_id)s] "
                        "%(message)s"
                    )
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["observability"],
                }
            },
            "root": {
                "handlers": ["default"],
                "level": resolved_level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": resolved_level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": logging.WARNING,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": resolved_level,
                    "propagate": False,
                },
                "rq.worker": {
                    "handlers": ["default"],
                    "level": resolved_level,
                    "propagate": False,
                },
            },
        }
    )
    _logging_configured = True


def _build_exporter_endpoint(otlp_endpoint: str | None, seq_uri: str | None) -> str | None:
    if otlp_endpoint:
        return otlp_endpoint
    if seq_uri:
        return f"{seq_uri.rstrip('/')}/ingest/otlp/v1/traces"
    return None


def configure_tracing(
    *,
    service_name: str,
    environment: str,
    enable_tracing: bool,
    otlp_endpoint: str | None,
    seq_uri: str | None = None,
) -> None:
    global _tracing_configured
    if _tracing_configured:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            DEPLOYMENT_ENVIRONMENT: environment,
            SERVICE_INSTANCE_ID: os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or socket.gethostname(),
        }
    )
    provider = TracerProvider(resource=resource)

    if enable_tracing:
        endpoint = _build_exporter_endpoint(otlp_endpoint, seq_uri)
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        else:
            logging.getLogger(__name__).warning(
                "Tracing is enabled but no OTLP endpoint is configured. "
                "Set OTEL_EXPORTER_OTLP_ENDPOINT or SEQ_URI to export traces."
            )

    trace.set_tracer_provider(provider)
    atexit.register(provider.shutdown)
    _tracing_configured = True


def configure_observability(
    *,
    service_name: str,
    environment: str,
    log_level: str,
    enable_tracing: bool,
    otlp_endpoint: str | None,
    seq_uri: str | None = None,
) -> None:
    configure_logging(log_level)
    configure_tracing(
        service_name=service_name,
        environment=environment,
        enable_tracing=enable_tracing,
        otlp_endpoint=otlp_endpoint,
        seq_uri=seq_uri,
    )


def instrument_fastapi_app(app: FastAPI) -> None:
    global _fastapi_instrumented
    if _fastapi_instrumented:
        return

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    _fastapi_instrumented = True


def instrument_sqlalchemy_engine(engine) -> None:
    global _sqlalchemy_instrumented
    if _sqlalchemy_instrumented:
        return

    SQLAlchemyInstrumentor().instrument(engine=engine)
    _sqlalchemy_instrumented = True


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token: Token[str | None] = _request_id_ctx.set(request_id)
    try:
        yield
    finally:
        _request_id_ctx.reset(token)


def serialize_current_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_trace_context(carrier: Mapping[str, str] | None) -> Context:
    return propagate.extract(carrier=carrier or {})


def get_tracer(name: str):
    return trace.get_tracer(name)
