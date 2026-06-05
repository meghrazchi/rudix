"""Connector platform domain package.

Importing this package ensures all provider adapters are registered.
"""
import app.domains.connectors.providers  # noqa: F401 – side-effect: registers adapters
