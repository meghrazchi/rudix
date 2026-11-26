"""Scenario ``chat_ws``: the streaming chat path over ``/api/v1/chat/ws``.

Locust has no WebSocket client, so this uses ``websockets.sync.client`` (installed with
``uvicorn[standard]``; gevent's monkey-patching makes it cooperative). Per task:

1. ``POST /api/v1/chat/ws-ticket`` for a single-use handshake ticket.
2. Connect to ``/api/v1/chat/ws?ticket=...`` and wait for ``connection.ready``.
3. Send ``chat.start`` with one question.
4. Report ``WS time_to_first_event`` (first non-heartbeat event after the send) and
   ``WS full_answer`` (``chat.completed``). ``chat.error`` and timeouts are failures.

The ticket is never logged and the Locust request name never contains it.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

from locust import task
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from common.auth import CONFIG, AuthenticatedUser
from common.config import API_PREFIX
from common.events import ScenarioFailure, fire

TICKET_PATH = f"{API_PREFIX}/chat/ws-ticket"
WS_PATH = f"{API_PREFIX}/chat/ws"
HEARTBEAT_EVENT = "heartbeat.ping"
READY_EVENT = "connection.ready"
COMPLETED_EVENT = "chat.completed"
ERROR_EVENTS = frozenset({"chat.error", "chat.cancelled"})


@dataclass
class AnswerProgress:
    """Pure state machine over outbound events, kept separate for unit tests."""

    first_event_seen: bool = False
    done: bool = False
    error: str | None = None

    def observe(self, event: dict[str, Any]) -> tuple[str, bool]:
        """Classify one event as ``heartbeat``, ``event``, ``completed`` or ``error``.

        The second value is true for the first non-heartbeat event after ``chat.start``.
        """
        name = str(event.get("event", ""))
        if name == HEARTBEAT_EVENT:
            return "heartbeat", False
        first = not self.first_event_seen
        self.first_event_seen = True
        if name == COMPLETED_EVENT:
            self.done = True
            return "completed", first
        if name in ERROR_EVENTS:
            self.done = True
            self.error = str(event.get("safe_error_code") or name)
            return "error", first
        return "event", first


def start_message(question: str, request_id: str) -> str:
    return json.dumps(
        {"command": "chat.start", "payload": {"question": question}, "request_id": request_id}
    )


class ChatWsUser(AuthenticatedUser):
    weight = CONFIG.weights["chat_ws"]

    def _ticket(self) -> str | None:
        with self.client.post(
            TICKET_PATH,
            headers=self.auth_headers(),
            name=f"POST {TICKET_PATH}",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return None
            return str(response.json()["ticket"])

    @task
    def ask_streaming(self) -> None:
        ticket = self._ticket()
        if ticket is None:
            return
        url = f"{self.config.ws_base_url}{WS_PATH}?ticket={ticket}"
        timeout = self.config.ws_answer_timeout_seconds
        started = time.perf_counter()
        phase = "connect"
        try:
            with connect(url, open_timeout=30, close_timeout=5) as ws:
                self._await_ready(ws, timeout)
                fire(self.environment, request_type="WS", name="connect", started=started)
                phase = "full_answer"
                started = time.perf_counter()
                self._ask(ws, timeout)
        except (WebSocketException, OSError, ScenarioFailure) as exc:
            # Connection refused, handshake rejected (4401/4429/4503) or dropped mid-answer.
            fire(
                self.environment,
                request_type="WS",
                name=phase,
                started=started,
                exception=ScenarioFailure(type(exc).__name__),
            )

    @staticmethod
    def _await_ready(ws: Any, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = json.loads(ws.recv(timeout=max(0.1, deadline - time.monotonic())))
            if event.get("event") == READY_EVENT:
                return
        raise ScenarioFailure("no connection.ready")

    def _ask(self, ws: Any, timeout: float) -> None:
        question = random.choice(self.config.questions)
        progress = AnswerProgress()
        started = time.perf_counter()
        ws.send(start_message(question, uuid.uuid4().hex))
        deadline = time.monotonic() + timeout
        try:
            while not progress.done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                kind, first = progress.observe(json.loads(ws.recv(timeout=remaining)))
                if kind == "heartbeat":
                    ws.send(json.dumps({"command": "heartbeat.pong"}))
                elif first:
                    fire(
                        self.environment,
                        request_type="WS",
                        name="time_to_first_event",
                        started=started,
                    )
        except TimeoutError:
            progress.error = "timeout"
        failure = ScenarioFailure(progress.error) if progress.error else None
        fire(
            self.environment,
            request_type="WS",
            name="full_answer",
            started=started,
            exception=failure,
        )
