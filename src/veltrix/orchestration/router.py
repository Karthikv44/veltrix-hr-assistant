"""Intent and route classification for employee queries."""

import re
from typing import Literal

from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext

logger = get_logger("router")

IntentType = Literal["rag", "leave_tool", "hybrid", "clarify", "refuse", "greeting"]

# Refusal keywords (prompt injection, bulk data, off-topic, special authority claims)
INJECTION_KEYWORDS = [
    "ignore your instructions",
    "system prompt",
    "hidden data",
    "bypass",
    "jailbreak",
    "reveal instructions",
]

BULK_DATA_KEYWORDS = [
    "everyone's balances",
    "everybody's balances",
    "all employees' leave",
    "all employee balances",
    "dump the database",
]

OFF_TOPIC_KEYWORDS = [
    "write python code",
    "solve this math problem",
    "who is the president",
    "weather in",
]

GREETING_REGEX = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|thanks|thank\s+you)\b[!.]*$",
    re.IGNORECASE,
)

LEAVE_TOOL_KEYWORDS = [
    "apply for leave",
    "apply leave",
    "book leave",
    "request leave",
    "cancel leave",
    "cancel my leave",
    "my leave balance",
    "remaining leave",
    "leave balance",
    "my pending requests",
    "my leave requests",
    "team's leave",
    "team leave",
]


class Router:
    """Classifies user intent into appropriate routing category."""

    @staticmethod
    def classify_intent(message: str, ctx: RequestContext) -> IntentType:
        """Deterministically inspect message for refusal, greeting, tool action, or RAG."""
        text = message.strip().lower()

        # 1. Greetings
        if GREETING_REGEX.match(text):
            return "greeting"

        # 2. Refusal: Prompt injections & hidden prompt probes
        if any(kw in text for kw in INJECTION_KEYWORDS):
            logger.info("Refusal triggered by injection keywords", employee_id=ctx.employee_id)
            return "refuse"

        # 3. Refusal: Bulk data requests
        if any(kw in text for kw in BULK_DATA_KEYWORDS):
            logger.info("Refusal triggered by bulk data keywords", employee_id=ctx.employee_id)
            return "refuse"

        # 4. Refusal: Off-topic requests
        if any(kw in text for kw in OFF_TOPIC_KEYWORDS):
            logger.info("Refusal triggered by off-topic keywords", employee_id=ctx.employee_id)
            return "refuse"

        # 5. Check for leave tool actions
        if any(kw in text for kw in LEAVE_TOOL_KEYWORDS):
            # If asking about policies combined with personal balance -> hybrid
            if "policy" in text or "allowance" in text or "accrual" in text:
                return "hybrid"
            return "leave_tool"

        # 6. Default to RAG for policy inquiries
        return "rag"
