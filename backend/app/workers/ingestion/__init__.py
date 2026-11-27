"""Staged, resumable document ingestion (R06-01).

``app.workers.document_tasks`` is the Celery facade; this package holds the stages
(``stages/``), the inline runner, the stage store, and the helpers moved out of the
single-pass worker.
"""
