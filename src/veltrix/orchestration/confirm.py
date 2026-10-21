"""State machine for two-step write confirmation (propose dry-run -> execute on confirm)."""

import re
from typing import Any

from veltrix.core.logging import get_logger
from veltrix.data.sessions import Proposal, SessionManager

logger = get_logger("confirm")

# Strict regex full-match for clear confirmations per Section 8.2:
# "yes", "confirm", "go ahead", "yep", "sure", "proceed", "please do"
CONFIRMATION_REGEX = re.compile(
    r"^\s*(?:yes|confirm|go\s+ahead|yep|sure|proceed|please\s+do|i\s+confirm|approved?)\s*[.!]?\s*$",
    re.IGNORECASE,
)

CANCEL_PROPOSAL_REGEX = re.compile(
    r"^\s*(?:no|cancel|nevermind|don't|stop|abort)\s*[.!]?\s*$",
    re.IGNORECASE,
)


class ConfirmationStateMachine:
    """Manages the two-step write flow:

    1. Propose: dry-run validate, store Proposal in app.db, set pending_confirmation: true.
    2. Execute: on immediate next affirmative confirmation, execute atomically and clear proposal.
    3. Modify: on parameter change, replace proposal.
    4. Anything else: discard proposal and process normally.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self.session_manager = session_manager

    def is_confirmation(self, message: str) -> bool:
        """Strict regex check for explicit user confirmation."""
        return bool(CONFIRMATION_REGEX.match(message.strip()))

    def is_cancellation(self, message: str) -> bool:
        """Strict check for explicit cancellation of proposal."""
        return bool(CANCEL_PROPOSAL_REGEX.match(message.strip()))

    def get_pending_proposal(self, session_id: str) -> Proposal | None:
        """Fetch pending proposal for session."""
        return self.session_manager.get_proposal(session_id)

    def save_proposal(
        self,
        session_id: str,
        employee_id: str,
        action_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist dry-run proposal waiting for confirmation."""
        self.session_manager.save_proposal(
            session_id=session_id,
            employee_id=employee_id,
            action_type=action_type,
            payload=payload,
        )

    def clear_proposal(self, session_id: str) -> None:
        """Discard or consume pending proposal."""
        self.session_manager.clear_proposal(session_id)
