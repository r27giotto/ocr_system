import cv2
import numpy as np
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt

from ui.overlay import draw_overlay
from core.models import RecognitionResult


class ImageView(QLabel):
    """显示原图 / 带 ROI 框的图；自动等比缩放"""
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #222; color: #888;")
        self.setText("等待图像…")
        self._current_frame: np.ndarray | None = None
        self._current_res: RecognitionResult | None = None

    def set_frame(self, frame: np.ndarray, name: str = ""):
        self._current_frame = frame
        self._current_res = None
        self._render(frame)

    def set_result(self, res: RecognitionResult, keep_frame: bool = False):
        self._current_res = res
        if keep_frame and res.frame is not None:
            self._current_frame = res.frame
        if res.frame is not None:
            vis = draw_overlay(res.frame, res)
            self._render(vis)

    def _render(self, img_bgr: np.ndarray):
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.setPixmap(pix.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._current_res is not None:
            self.set_result(self._current_res, keep_frame=True)
        elif self._current_frame is not None:
            self._render(self._current_frame)