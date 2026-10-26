from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class SecurityEvent(str, Enum):
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    TENANT_VIOLATION = "TENANT_VIOLATION"
    KILL_SWITCH = "KILL_SWITCH"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    WEBHOOK_INVALID = "WEBHOOK_INVALID"
    LOOP_DETECTED = "LOOP_DETECTED"
    DNC_BLOCKED = "DNC_BLOCKED"

@dataclass(frozen=True)
class LoopLimits:
    max_actions: int = 20
    max_llm_calls: int = 10
    max_messages: int = 5

def check_loop(*, actions: int, llm_calls: int, messages: int, limits: LoopLimits = LoopLimits()) -> None:
    if actions > limits.max_actions or llm_calls > limits.max_llm_calls or messages > limits.max_messages:
        raise RuntimeError(SecurityEvent.LOOP_DETECTED.value)

def check_tenant(expected: str, actual: str) -> None:
    if expected != actual:
        raise PermissionError(SecurityEvent.TENANT_VIOLATION.value)

def check_kill_switch(enabled: bool) -> None:
    if enabled:
        raise RuntimeError(SecurityEvent.KILL_SWITCH.value)

def check_dnc(is_dnc: bool) -> None:
    if is_dnc:
        raise PermissionError(SecurityEvent.DNC_BLOCKED.value)

def validate_webhook_signature(valid: bool) -> None:
    if not valid:
        raise PermissionError(SecurityEvent.WEBHOOK_INVALID.value)

def detect_prompt_injection(text: str) -> bool:
    t = text.lower()
    patterns = (
        "ignore previous instructions", "ignore all previous instructions",
        "system prompt", "reveal your instructions", "developer message",
        "bypass your rules",
    )
    return any(p in t for p in patterns)
