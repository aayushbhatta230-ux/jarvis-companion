"""Structured result for real (verified) screen-control actions.

This is the low-level contract between the screen-control executor and the
capability registry. It lets JARVIS honestly distinguish between:

* an action that *did* change the screen and was verified,
* an action that ran but could not be verified,
* an action that clearly failed (target not found, ambiguous, no permission),
* an action that was blocked because it needs confirmation.

``verification`` is meaningfully one of True / False / None::

    True  -> post-action perception confirmed the expected change.
    False -> post-action perception shows the action did NOT take effect.
    None  -> verification genuinely could not be determined.

`None` must never be reported as success, and `False` must never be
silently converted to a success message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    success: bool
    status: str  # completed, target_not_found, ambiguous, permission_denied, confirmation_required, failed, verification_failed
    action: str
    error: str | None = None
    verification: bool | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_tool_fields(self) -> dict[str, Any]:
        """Project onto the fields the capability layer consumes."""
        return {
            "success": self.success,
            "status": self.status,
            "error": self.error,
            "verification": self.verification,
            "arguments": self.arguments,
            "message": self.message,
        }

    def __str__(self) -> str:
        return self.message or f"{self.action}: {self.status}"