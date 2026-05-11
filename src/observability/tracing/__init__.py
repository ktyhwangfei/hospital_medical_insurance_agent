from __future__ import annotations

from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _OTLP_AVAILABLE = True
except ImportError:
    _OTLP_AVAILABLE = False

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter

    _JAEGER_AVAILABLE = True
except ImportError:
    _JAEGER_AVAILABLE = False


def setup_tracing(
    service_name: str = 'medical-insurance-ai-agent',
    otlp_endpoint: str | None = None,
    jaeger_agent_host: str | None = None,
    jaeger_agent_port: int = 6831,
) -> Any | None:
    """Configure OpenTelemetry SDK and return the tracer provider.

    Args:
        service_name: Name of the service for tracing.
        otlp_endpoint: Optional OTLP HTTP endpoint (e.g. http://localhost:4318).
        jaeger_agent_host: Optional Jaeger agent host.
        jaeger_agent_port: Jaeger agent port (default 6831).

    Returns:
        Configured TracerProvider, or None if OpenTelemetry is not installed.
    """
    if not _OTEL_AVAILABLE:
        return None

    resource = Resource.create({'service.name': service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint and _OTLP_AVAILABLE:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    if jaeger_agent_host and _JAEGER_AVAILABLE:
        jaeger_exporter = JaegerExporter(
            agent_host_name=jaeger_agent_host,
            agent_port=jaeger_agent_port,
        )
        provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))

    trace.set_tracer_provider(provider)
    return provider


def get_tracer(service_name: str = 'medical-insurance-ai-agent') -> Any | None:
    """Get a tracer instance if OpenTelemetry is available."""
    if not _OTEL_AVAILABLE:
        return None
    return trace.get_tracer(service_name)
