from dataclasses import dataclass
from typing import Tuple, Optional
import cv2
import numpy as np
import math

@dataclass
class PreprocessConfig:
    roi_size: int = 116
    scale: float = 1.0
    clahe_clip: float = 2.0
    clahe_grid: Tuple[int, int] = (8, 8)
    min_radius: int = 20
    max_radius: int = 200

class Preprocessor:
    def __init__(self, cfg: PreprocessConfig):
        self.cfg = cfg
        self._clahe = cv2.createCLAHE(cfg.clahe_clip, cfg.clahe_grid)

    def enhance(self, gray: np.ndarray) -> np.ndarray:
        return self._clahe.apply(gray)

    def find_roi(self, gray: np.ndarray):
        """返回 (roi, (cx, cy, r), (x1, y1, x2, y2)) 或 None"""
        _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((5, 5), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        (cx, cy), r = cv2.minEnclosingCircle(largest)
        cx, cy, r = int(cx), int(cy), int(r)

        if r < self.cfg.min_radius or r > self.cfg.max_radius:
            return None

        half = self.cfg.roi_size // 2
        x1, y1 = max(0, cx - half), max(0, cy - half)
        x2, y2 = min(gray.shape[1], cx + half), min(gray.shape[0], cy + half)
        if x2 - x1 < self.cfg.roi_size or y2 - y1 < self.cfg.roi_size:
            return None

        return gray[y1:y2, x1:x2], (cx, cy, r), (x1, y1, x2, y2)

    def rotate(self, img: np.ndarray, angle: int,
               scale: Optional[float] = None) -> np.ndarray:
        if scale is None:
            scale = self.cfg.scale
        h, w = img.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        M = cv2.getRotationMatrix2D((cx, cy), angle, scale)

        rad = math.radians(angle)
        cos_a, sin_a = abs(math.cos(rad)), abs(math.sin(rad))
        new_w = int(scale * (h * sin_a + w * cos_a))
        new_h = int(scale * (w * sin_a + h * cos_a))

        M[0, 2] += new_w / 2.0 - cx
        M[1, 2] += new_h / 2.0 - cy

        return cv2.warpAffine(img, M, (new_w, new_h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)

    def build_variants(self, roi: np.ndarray, angles: Tuple[int, ...]):
        """生成所有角度变体（0° 直接用原 ROI，不放大）"""
        ordered = sorted(angles, key=lambda a: abs(a))
        variants = []
        for angle in ordered:
            if angle == 0:
                img = roi
            else:
                img = self.rotate(roi, angle, self.cfg.scale)
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            variants.append((img, angle))
        return variants