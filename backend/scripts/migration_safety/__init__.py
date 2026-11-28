"""Migration safety check helpers (0.8.0, R08-08); the CLI is ``check_migration_safety.py``.

- ``rules``: rule names and the override marker syntax.
- ``models``: tables and columns the application models reference (working tree or git ref).
- ``sql``: findings in raw SQL passed to ``op.execute`` or ``connection.execute``.
- ``analyzer``: walks a migration's ``upgrade()`` (and the module helpers it calls).
- ``policy``: large tables, markers, the allowlist, and the final findings.
"""
