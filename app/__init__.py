"""DF Local Foundation — HTTP application package.

A thin, read-only control-plane surface over the foundation's lifecycle/health layer. It exposes
ONLY the declared health surface (contracts/health.schema.json) and never customer or domain data.
"""

from .main import create_app

__all__ = ["create_app"]
