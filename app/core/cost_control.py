from dataclasses import dataclass

@dataclass(frozen=True)
class CostBudget:
    monthly_limit_eur: float
    warning_ratio: float = 0.80
    throttle_ratio: float = 0.90
    hard_stop_ratio: float = 1.00

    def ratio(self, spent_eur: float) -> float:
        return 0.0 if self.monthly_limit_eur <= 0 else spent_eur / self.monthly_limit_eur

    def state(self, spent_eur: float) -> str:
        r = self.ratio(spent_eur)
        if r >= self.hard_stop_ratio: return "HARD_STOP"
        if r >= self.throttle_ratio: return "THROTTLE"
        if r >= self.warning_ratio: return "WARNING"
        return "NORMAL"
