"""Rudix load-test entry point (R03-09).

Run one scenario by naming its user class, or all of them weighted by
``RUDIX_LOAD_SCENARIO_WEIGHTS``::

    locust -f ci/load/locustfile.py --headless -u 10 -r 2 -t 5m ChatWsUser

See ``ci/load/README.md`` for the stack, the seeded account, and the report workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Locust puts this directory on sys.path; keep that true for `python -c "import ..."` too.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from common.auth import CONFIG  # noqa: E402
from scenarios.admin_dashboard import AdminDashboardUser  # noqa: E402
from scenarios.chat_http import ChatHttpUser  # noqa: E402
from scenarios.chat_ws import ChatWsUser  # noqa: E402
from scenarios.documents_list import DocumentsListUser  # noqa: E402
from scenarios.upload_ingest import UploadIngestUser  # noqa: E402

USER_CLASSES = {
    "chat_ws": ChatWsUser,
    "chat_http": ChatHttpUser,
    "documents_list": DocumentsListUser,
    "upload_ingest": UploadIngestUser,
    "admin_dashboard": AdminDashboardUser,
}

# A weight of 0 removes the scenario from a mixed run. To run one scenario on its own,
# name its class on the command line and leave its weight above 0.
for _name, _cls in USER_CLASSES.items():
    if CONFIG.weights[_name] == 0:
        _cls.abstract = True
del _name, _cls

__all__ = [
    "AdminDashboardUser",
    "ChatHttpUser",
    "ChatWsUser",
    "DocumentsListUser",
    "UploadIngestUser",
]
