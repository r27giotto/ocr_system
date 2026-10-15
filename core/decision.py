from typing import Set


class DecisionMaker:
    """
    输入：识别结果（number 字符串）
    输出：1 / 0
    规则：number ∈ target_set → 1；否则 → 0
    """
    def __init__(self, target_numbers: Set[str],
                 valid_min: int = 1, valid_max: int = 48):
        self.valid_min = valid_min
        self.valid_max = valid_max
        self.set_targets(target_numbers)

    def set_targets(self, targets: Set[str]) -> None:
        self._targets = {str(t).strip() for t in targets if str(t).strip()}

    @property
    def targets(self) -> Set[str]:
        return set(self._targets)

    def decide(self, number: str, status: str = "ok") -> int:
        if status != "ok" or not number or number == "0":
            return 0
        try:
            n = int(number)
        except ValueError:
            return 0
        if not (self.valid_min <= n <= self.valid_max):
            return 0
        return 1 if number in self._targets else 0

    def is_hit(self, number: str) -> bool:
        return number in self._targets