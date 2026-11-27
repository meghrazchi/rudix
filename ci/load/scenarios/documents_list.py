"""Scenario ``documents_list``: paginate ``GET /api/v1/documents``."""

from __future__ import annotations

import random

from locust import task

from common.auth import CONFIG, AuthenticatedUser
from common.config import API_PREFIX

DOCUMENTS_PATH = f"{API_PREFIX}/documents"
PAGE_SIZE = 20


def next_offset(total: int, page_size: int = PAGE_SIZE) -> int:
    """A random page offset within ``total`` documents (0 when there is one page)."""
    pages = max(1, -(-total // page_size))
    return random.randrange(pages) * page_size


class DocumentsListUser(AuthenticatedUser):
    weight = CONFIG.weights["documents_list"]

    def on_start(self) -> None:
        super().on_start()
        self.total_documents = 0

    @task(3)
    def first_page(self) -> None:
        self._list(0)

    @task(1)
    def random_page(self) -> None:
        self._list(next_offset(self.total_documents))

    def _list(self, offset: int) -> None:
        with self.client.get(
            DOCUMENTS_PATH,
            params={"limit": PAGE_SIZE, "offset": offset},
            headers=self.auth_headers(),
            name=f"GET {DOCUMENTS_PATH}",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return
            self.total_documents = int(response.json().get("total", 0))
