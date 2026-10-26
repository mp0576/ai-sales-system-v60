from dataclasses import dataclass
from typing import Any, Callable
import time

@dataclass(frozen=True)
class WorkerConfig:
    max_attempts: int = 5
    base_backoff_seconds: int = 5
    max_backoff_seconds: int = 900
    lease_seconds: int = 120

class RetryableError(Exception):
    pass

class PermanentError(Exception):
    pass

@dataclass
class ExecutionResult:
    status: str
    attempts: int
    output: dict[str, Any]
    error: str | None = None

class WorkerRuntime:
    """Provider-agnostic execution policy. DB claiming is deliberately external."""
    def __init__(self, config: WorkerConfig | None = None, sleep: Callable[[float], None] = time.sleep):
        self.config = config or WorkerConfig()
        self.sleep = sleep

    def backoff(self, attempt: int) -> int:
        return min(self.config.max_backoff_seconds, self.config.base_backoff_seconds * (2 ** max(0, attempt - 1)))

    def execute(self, handler: Callable[[dict[str, Any]], dict[str, Any]], payload: dict[str, Any], attempt: int = 1) -> ExecutionResult:
        try:
            return ExecutionResult("SUCCEEDED", attempt, handler(payload))
        except PermanentError as exc:
            return ExecutionResult("FAILED", attempt, {}, str(exc))
        except RetryableError as exc:
            if attempt >= self.config.max_attempts:
                return ExecutionResult("DEAD_LETTER", attempt, {}, str(exc))
            return ExecutionResult("RETRY", attempt, {}, str(exc))

    def run_with_retries(self, handler: Callable[[dict[str, Any]], dict[str, Any]], payload: dict[str, Any]) -> ExecutionResult:
        for attempt in range(1, self.config.max_attempts + 1):
            result = self.execute(handler, payload, attempt)
            if result.status == "RETRY":
                self.sleep(self.backoff(attempt))
                continue
            return result
        return ExecutionResult("DEAD_LETTER", self.config.max_attempts, {}, "retry budget exhausted")
