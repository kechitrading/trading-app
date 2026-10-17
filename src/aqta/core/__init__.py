"""Shared kernel: settings, logging, time (IST), ids, errors, clock, hashing, db and redis.

``aqta.core`` is the only package whose submodules may be imported directly by other modules
(e.g. ``from aqta.core.settings import Settings``); keeping DB/Redis imports in their own
submodules means domain code that needs a ``Clock`` never pulls in SQLAlchemy.
"""
