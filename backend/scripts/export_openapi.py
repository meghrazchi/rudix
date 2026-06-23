#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to JSON without starting any services.

Sets stub values for required config fields so pydantic-settings can load
without a .env file or live infrastructure. If a .env file exists in the
project root or backend directory it is loaded first (real values take
precedence).

Usage:
    python scripts/export_openapi.py [output_path]

    output_path defaults to stdout if omitted or "-", otherwise writes to file.
"""

import json
import os
import sys
from pathlib import Path

# Stub every required field that has no default.  These values satisfy
# pydantic type validation and are never used for actual connections.
_STUBS: dict[str, str] = {
    "API_BASE_URL": "http://localhost:8000",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "postgresql+asyncpg://x:x@localhost/x",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "documents",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "MINIO_BUCKET": "documents",
    "RABBITMQ_URL": "amqp://x:x@localhost:5672//",
    "REDIS_URL": "redis://localhost:6379/0",
}

for key, value in _STUBS.items():
    os.environ.setdefault(key, value)

from app.main import app  # noqa: E402

schema = app.openapi()
serialized = json.dumps(schema, indent=2) + "\n"

output = sys.argv[1] if len(sys.argv) > 1 else "-"
if output == "-":
    sys.stdout.write(serialized)
else:
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(serialized)
    print(f"OpenAPI schema written to {dest}", file=sys.stderr)
