"""Celery worker layer: app factory, task modules, and Redis rate limiting.

Workers use the sync SQLAlchemy engine only (see app.db) — the async factory
is banned in this package by ruff's banned-api rule.
"""
