'''Action state enumeration and utilities for JARVIS.'''

from enum import Enum

class ActionState(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

