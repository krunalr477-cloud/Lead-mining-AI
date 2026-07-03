"""Pure, exhaustively-testable pipeline logic: validation, dedupe, sales-ready rules.

Everything in this package is side-effect free and free of Celery/DB imports so the
correctness core can be unit-tested in isolation. Workers call these functions and
persist the results; the functions themselves never touch a session or a queue.
"""
