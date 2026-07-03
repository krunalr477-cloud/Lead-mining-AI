"""Outreach subsystem: template rendering, scheduling, sending, bounce/reply parsing.

Pure logic (renderer, bounce parser) lives beside I/O-driven modules (scheduler,
sender, reply monitor) that lean on the Gmail client and DB session. Celery tasks
under ``app.workers.tasks.campaign`` / ``bounce`` orchestrate these.
"""
