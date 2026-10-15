from dataclasses import dataclass, field
from typing import Optional, Tuple
import time
import numpy as np

@dataclass
class RecognitionResult:
    """单帧识别的完整结果"""
    filename: str = ""
    number: str = ""                 # 清洗后的数字字符串，如 "12"
    confidence: float = 0.0
    angle: int = 0                   # 命中的旋转角度
    status: str = "ok"               # ok / no_number / circle_not_found / error
    output_value: int = 0            # ★ 决策结果 1 / 0
    hit: bool = False
    elapsed_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    roi_box: Optional[Tuple[int, int, int, int]] = None   # x1,y1,x2,y2
    frame: Optional[np.ndarray] = None                    # 用于历史缩略图
    error_msg: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"