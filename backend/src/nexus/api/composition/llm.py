"""Application composition for the LLM capability."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.config.settings import Settings
from nexus.llm.application import Generate, Stream
from nexus.llm.infrastructure.gateway_factory import create_llm_gateway
from nexus.llm.ports import LLMGateway


@dataclass(frozen=True)
class LLMComposition:
    """Application-scoped LLM dependencies composed at startup."""

    gateway: LLMGateway
    generate: Generate
    stream: Stream


def build_llm_composition(
    app_settings: Settings,
    gateway: LLMGateway | None = None,
) -> LLMComposition:
    """Build LLM use cases around one shared gateway instance."""

    resolved_gateway = (
        gateway if gateway is not None else create_llm_gateway(app_settings.llm_gateway)
    )
    return LLMComposition(
        gateway=resolved_gateway,
        generate=Generate(gateway=resolved_gateway),
        stream=Stream(gateway=resolved_gateway),
    )
