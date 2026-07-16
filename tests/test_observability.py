from app.observability import _GRPC_OTLP_PROTOCOL, _HTTP_OTLP_PROTOCOL, _normalize_signal_endpoint, _resolve_otlp_protocol


def test_resolve_otlp_protocol_prefers_explicit_value():
    assert _resolve_otlp_protocol("grpc", "https://localhost:21293", None) == _GRPC_OTLP_PROTOCOL
    assert _resolve_otlp_protocol("http/protobuf", "https://localhost:21293", None) == _HTTP_OTLP_PROTOCOL


def test_resolve_otlp_protocol_detects_http_signal_path():
    assert _resolve_otlp_protocol("invalid", "https://localhost:4318/v1/traces", None) == _HTTP_OTLP_PROTOCOL
    assert _resolve_otlp_protocol("invalid", None, "http://localhost:5341/ingest/otlp/v1/traces") == _HTTP_OTLP_PROTOCOL


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
