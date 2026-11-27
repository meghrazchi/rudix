"""Connector sync components behind ``ConnectorSyncEngine`` (R06-11).

``planner`` (jobs, triggers, runs), ``schedule`` (due-job polling), ``runner`` (run
execution), ``fetcher`` (provider paging, OAuth refresh), ``differ`` (change detection,
conflicts, tombstones), ``writer`` (file ingestion, run outcomes, audit).
"""

from app.domains.connectors.services.sync.common import SyncEngineError, SyncRunResult

__all__ = ["SyncEngineError", "SyncRunResult"]
