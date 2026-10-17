"""HTTP API edge (FastAPI). Only this package and ``aqta.worker`` may import web frameworks."""

from aqta.api.app import create_app
from aqta.api.container import Container, build_container, build_in_memory_container

__all__ = ["Container", "build_container", "build_in_memory_container", "create_app"]
