"""Shared API dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from nexus.composition.root import AppContainer
from nexus.events import EventPublisher


def get_container(request: Request) -> AppContainer:
    """Return the single application composition container."""

    return request.app.state.container


AppContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_event_publisher(container: AppContainerDep) -> EventPublisher:
    """Return the application-scoped event publisher for request dependencies."""

    return container.event_publisher
