"""Scenario ``upload_ingest``: upload a generated TXT file and wait until it is indexed.

The ingest duration (upload accepted to ``indexed``) is reported as a custom event with
request type ``INGEST``. Any non-``indexed`` terminal status, or no terminal status within
``RUDIX_LOAD_INGEST_TIMEOUT_SECONDS``, is recorded as a failure.
"""

from __future__ import annotations

import time
import uuid

from locust import task

from common.auth import CONFIG, AuthenticatedUser
from common.config import API_PREFIX
from common.events import ScenarioFailure, fire

UPLOAD_PATH = f"{API_PREFIX}/documents/upload"
STATUS_NAME = f"GET {API_PREFIX}/documents/{{document_id}}/status"
POLL_INTERVAL_SECONDS = 2.0
SUCCESS_STATUS = "indexed"
FAILURE_STATUSES = frozenset(
    {
        "failed",
        "quarantined",
        "blocked",
        "infected",
        "extraction_failed",
        "unsupported",
        "skipped",
        "deleted",
    }
)


def build_document(marker: str) -> bytes:
    """A small unique TXT body; the marker defeats duplicate detection."""
    paragraphs = [
        f"Load test document {marker}.",
        "Refund policy: customers may request a refund within 30 days of purchase.",
        "Retention: support tickets are kept for 24 months, then deleted.",
        "Incident response is owned by the platform operations team.",
    ]
    return ("\n\n".join(paragraphs * 5) + "\n").encode("utf-8")


class UploadIngestUser(AuthenticatedUser):
    weight = CONFIG.weights["upload_ingest"]

    @task
    def upload_and_wait(self) -> None:
        marker = uuid.uuid4().hex
        files = {"file": (f"load-{marker}.txt", build_document(marker), "text/plain")}
        started = time.perf_counter()
        with self.client.post(
            UPLOAD_PATH,
            files=files,
            headers=self.auth_headers(),
            name=f"POST {UPLOAD_PATH}",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"HTTP {response.status_code}")
                return
            document_id = str(response.json()["document_id"])

        error = self._wait_for_terminal(document_id)
        fire(
            self.environment,
            request_type="INGEST",
            name="upload_to_indexed",
            started=started,
            exception=error,
        )

    def _wait_for_terminal(self, document_id: str) -> ScenarioFailure | None:
        deadline = time.monotonic() + self.config.ingest_timeout_seconds
        path = f"{API_PREFIX}/documents/{document_id}/status"
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            with self.client.get(
                path, headers=self.auth_headers(), name=STATUS_NAME, catch_response=True
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    continue
                status = str(response.json().get("status", ""))
            if status == SUCCESS_STATUS:
                return None
            if status in FAILURE_STATUSES:
                return ScenarioFailure(f"terminal status {status}")
        return ScenarioFailure("ingest timeout")
