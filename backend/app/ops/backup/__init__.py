"""Encrypted backups to an off-host bucket, markers, and freshness (0.8.0, R08-06).

- ``crypto``: streaming AES-256-GCM file format (``RUDIXBK1``).
- ``store``: the backup bucket client (boto3) and server-side encryption flags.
- ``markers``: ``<prefix>/<kind>/latest.json`` (contract 5.2.9).
- ``postgres``, ``qdrant``, ``objects``: one runner per kind.
- ``freshness``: marker age per kind and the freshness counter.

Nothing here runs on the request path. The CLIs live in ``backend/scripts/`` and the beat
task in ``app/workers/backup_tasks.py``.
"""
