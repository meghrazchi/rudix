"""Scenario ``admin_dashboard``: the admin usage dashboard and observability snapshot.

Both routes require the ``owner`` or ``admin`` role, so run this scenario with an admin
account (the bootstrap admin is an owner).
"""

from __future__ import annotations

from locust import task

from common.auth import CONFIG, AuthenticatedUser
from common.config import API_PREFIX

USAGE_DASHBOARD_PATH = f"{API_PREFIX}/admin/usage/dashboard"
OBSERVABILITY_PATH = f"{API_PREFIX}/admin/observability"


class AdminDashboardUser(AuthenticatedUser):
    weight = CONFIG.weights["admin_dashboard"]

    def _get(self, path: str) -> None:
        with self.client.get(
            path, headers=self.auth_headers(), name=f"GET {path}", catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def usage_dashboard(self) -> None:
        self._get(USAGE_DASHBOARD_PATH)

    @task(1)
    def observability(self) -> None:
        self._get(OBSERVABILITY_PATH)
