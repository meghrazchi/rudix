"""Scenario ``chat_http``: one grounded answer per task through ``POST /api/v1/chat``."""

from __future__ import annotations

import random

from locust import task

from common.auth import CONFIG, AuthenticatedUser
from common.config import API_PREFIX

CHAT_PATH = f"{API_PREFIX}/chat"


class ChatHttpUser(AuthenticatedUser):
    weight = CONFIG.weights["chat_http"]

    @task
    def ask(self) -> None:
        payload = {"question": random.choice(self.config.questions)}
        with self.client.post(
            CHAT_PATH,
            json=payload,
            headers=self.auth_headers(),
            name=f"POST {CHAT_PATH}",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
