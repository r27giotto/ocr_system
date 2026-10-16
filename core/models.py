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

    @property
    def output_text(self) -> str:
        """`output_value`（1/0）在界面上的显示文本。**只用于显示，不改串口与 CSV。**

        约定（用户 m01391）：**0 → "G"，1 → "NG"**。

        注意「识别失败」这一档：`circle_not_found` / `no_number` / `read_failed` / `error`
        时 `output_value` 也是 0，但那**不是良品**，只是没判出来。
        若照搬映射显示成绿色的 "G"，等于把「没看清」误报成良品
        （设计文档 §2 反目标 A2 / §11 缺陷 D1）。
        所以这一档单独显示 "?"，颜色与 G / NG 都不同，让操作员一眼能分辨。
        """
        if self.status != "ok":
            return "?"
        return "NG" if self.output_value == 1 else "G"