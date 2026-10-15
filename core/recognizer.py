from dataclasses import dataclass
from typing import Tuple, Optional

import cv2

from core.engine import EngineManager
from core.parsers import parse_ori_output, parse_rec_output
from core.preprocess import Preprocessor


@dataclass
class RecognizerConfig:
    angles: Tuple[int, ...] = (-90, -60, -30, 0, 30, 60, 90, 180)
    conf_threshold: float = 0.6
    early_exit_conf: float = 0.98
    valid_min: int = 1
    valid_max: int = 48
    drop_zero: bool = True


class Recognizer:
    def __init__(self, engine: EngineManager, pre: Preprocessor,
                 cfg: RecognizerConfig):
        self.engine = engine
        self.pre = pre
        self.cfg = cfg
        self.rec_model_name = ""
        self.ori_model_name = ""

    def set_models(self, rec_name: str, ori_name: str) -> None:
        self.rec_model_name = rec_name
        self.ori_model_name = ori_name

    def set_angles(self, angles: Tuple[int, ...]) -> None:
        """GUI 角度勾选变化时调用"""
        self.cfg.angles = tuple(sorted(set(angles), key=lambda a: abs(a)))

    def set_conf_threshold(self, v: float) -> None:
        self.cfg.conf_threshold = float(v)

    def recognize(self, roi) -> Optional[Tuple[str, float, int]]:
        """
        与旧脚本 ocr_best_result 逻辑完全一致：
        1. 构建变体（按 |angle| 升序）
        2. 每个变体：方向分类 → 必要时转 180° → 识别
        3. 过滤低置信度、非数字、'0'
        4. 0° 高置信度且有效范围内 → 立即返回
        5. 否则按 score 降序，返回第一个在 [valid_min, valid_max] 的候选
        """
        rec = self.engine.get_rec(self.rec_model_name)
        ori = self.engine.get_ori(self.ori_model_name)

        variants = self.pre.build_variants(roi, self.cfg.angles)
        candidates = []

        for img, angle in variants:
            ori_res = list(ori.predict([img]))
            fixed = img
            if ori_res and parse_ori_output(ori_res[0]) == 1:
                fixed = cv2.rotate(img, cv2.ROTATE_180)

            rec_res = list(rec.predict([fixed]))
            if not rec_res:
                continue

            for text, score in parse_rec_output(rec_res[0]):
                if score < self.cfg.conf_threshold:
                    continue
                cleaned = "".join(ch for ch in text if ch.isdigit())
                if not cleaned:
                    continue
                if self.cfg.drop_zero and cleaned == "0":
                    continue
                candidates.append((cleaned, score, angle))

                if (angle == 0
                        and score >= self.cfg.early_exit_conf
                        and self._in_range(cleaned)):
                    return (cleaned, score, angle)

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        for cleaned, score, angle in candidates:
            if self._in_range(cleaned):
                return (cleaned, score, angle)

        return None

    def _in_range(self, number_str: str) -> bool:
        try:
            n = int(number_str)
        except (ValueError, TypeError):
            return False
        return self.cfg.valid_min <= n <= self.cfg.valid_max