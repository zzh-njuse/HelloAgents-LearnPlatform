"""Shared product contracts — single canonical source for both API and MCP images.

Per correction 004 §2: both the API/worker Docker image and the execution MCP
Docker image must import from this single package. No fallback Pydantic models,
no duplicated schemas, no "equivalent" hand-written JSON.

This package contains ONLY pure-Python + pydantic definitions — no I/O, no
database, no settings, no framework imports. Both images COPY/install it.
"""
