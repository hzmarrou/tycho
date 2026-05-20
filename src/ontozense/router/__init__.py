"""File router — classifies incoming files by which Source should handle them."""

from .router import (
    Router,
    RoutingDecision,
    Source,
    route_file,
)

__all__ = [
    "Router",
    "RoutingDecision",
    "Source",
    "route_file",
]
