import cv2
from PyQt6.QtWidgets import (
    QGroupBox, QScrollArea, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSizePolicy
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from ui.overlay import draw_overlay
from core.models import RecognitionResult


class HistoryItem(QWidget):
    clicked = pyqtSignal(object)
    THUMB_W, THUMB_H = 160, 120

    def __init__(self, res: RecognitionResult):
        super().__init__()
        self.res = res
        self.setFixedWidth(180)

        # 1) 画框 + 结果叠加 + 缩放
        if res.frame is not None:
            vis = draw_overlay(res.frame, res)
            thumb = cv2.resize(vis, (self.THUMB_W, self.THUMB_H),
                               interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            self.thumb_label = QLabel()
            self.thumb_label.setPixmap(QPixmap.fromImage(qimg))
            self.thumb_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        else:
            self.thumb_label = QLabel("无图")
            self.thumb_label.setFixedSize(self.THUMB_W, self.THUMB_H)

        # 2) 文字信息
        num_text = res.number or "--"
        info = f"{res.filename[:20]}\n{num_text} → {res.output_value}"
        self.info_label = QLabel(info)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)

        # 3) 边框颜色标识决策结果
        if res.status != "ok":
            border = "#e74c3c"    # 红：异常
        elif res.output_value == 1:
            border = "#2ecc71"    # 绿：命中
        else:
            border = "#bdc3c7"    # 灰：未命中
        self.setStyleSheet(
            f"QWidget {{ border: 2px solid {border}; border-radius: 4px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self.thumb_label)
        v.addWidget(self.info_label)

    def mousePressEvent(self, e):
        self.clicked.emit(self.res)


class HistoryPanel(QGroupBox):
    item_clicked = pyqtSignal(object)
    MAX_ITEMS = 200

    def __init__(self):
        super().__init__("检测结果历史")
        self.setFixedHeight(190)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.container = QWidget()
        self.layout = QHBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.container)

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self.scroll)

    def add_result(self, res: RecognitionResult):
        item = HistoryItem(res)
        item.clicked.connect(self.item_clicked.emit)
        self.layout.addWidget(item)

        # 限制数量
        while self.layout.count() > self.MAX_ITEMS:
            old = self.layout.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        # 自动滚动到最右
        QTimer.singleShot(
            0,
            lambda: self.scroll.horizontalScrollBar().setValue(
                self.scroll.horizontalScrollBar().maximum()))

    def clear(self):
        while self.layout.count():
            it = self.layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()