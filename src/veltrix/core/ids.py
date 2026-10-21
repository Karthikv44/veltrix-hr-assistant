"""Identifier generation utilities for requests and leave records."""

import uuid


def generate_request_id() -> str:
    """Generate a random unguessable UUID4 request identifier."""
    return str(uuid.uuid4())


def generate_leave_request_id() -> str:
    """Generate a random unguessable UUID4 leave request identifier."""
    return f"req_{uuid.uuid4().hex[:12]}"
