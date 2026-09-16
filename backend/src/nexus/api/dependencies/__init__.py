"""Shared API dependencies."""

from fastapi import Request

from nexus.events import EventPublisher


def get_event_publisher(request: Request) -> EventPublisher:
    """Return the application-scoped event publisher for request dependencies."""
    return request.app.state.event_publisher
