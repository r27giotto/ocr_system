import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QGroupBox, QScrollArea, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSizePolicy, QPushButton
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from ui.overlay import draw_overlay
from core.models import RecognitionResult


class HistoryItem(QWidget):
    """单条历史记录：缩略图 + 「数字 → 1/0」。

    缩略图尺寸**固定**（THUMB_W x THUMB_H），不随历史区和窗口的大小变化。
    原图按比例缩放后居中放进这块固定画布，所以既不会被拉伸变形，
    也不会因为拉高历史区就跟着变大。原始帧一直在 res.frame 里。
    """

    clicked = pyqtSignal(object)

    THUMB_W = 120
    THUMB_H = 120
    ITEM_W = THUMB_W + 12          # 左右各 6px 内边距

    def __init__(self, res: RecognitionResult):
        super().__init__()
        self.res = res
        self.setFixedWidth(self.ITEM_W)
        # 宽高都由内容决定，历史区变高变矮都不再影响它
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # 让 QWidget 子类也能绘制自己的样式表边框
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # 1) 缩略图
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background:#20242b; color:#888;")
        self.thumb_label.setFixedSize(self.THUMB_W, self.THUMB_H)

        # 2) 文字信息
        num_text = res.number or "--"
        self.info_label = QLabel(f"{res.filename[:14]}\n{num_text} → {res.output_value}")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)

        # 3) 边框颜色标识决策结果（用 objectName 把选择器限制在本控件上，
        #    否则 QWidget 选择器会连子控件一起画边框）
        self.setObjectName("historyItem")
        if res.status != "ok":
            border = "#e74c3c"    # 红：异常
        elif res.output_value == 1:
            border = "#2ecc71"    # 绿：命中
        else:
            border = "#bdc3c7"    # 灰：未命中
        self.setStyleSheet(
            f"#historyItem {{ border: 2px solid {border}; border-radius: 4px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(3)
        v.addWidget(self.thumb_label)
        v.addWidget(self.info_label)

        self._render_thumb()

    # ---------- 缩略图 ----------
    @property
    def thumb_size(self) -> tuple:
        return (self.THUMB_W, self.THUMB_H)

    def _render_thumb(self):
        w, h = self.THUMB_W, self.THUMB_H
        if self.res.frame is None:
            self.thumb_label.setText("无图")
            return

        self.thumb_label.setText("")
        vis = draw_overlay(self.res.frame, self.res)
        ih, iw = vis.shape[:2]
        scale = min(w / iw, h / ih)
        nw = max(1, int(round(iw * scale)))
        nh = max(1, int(round(ih * scale)))
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
        small = cv2.resize(vis, (nw, nh), interpolation=interp)

        # 居中放进固定尺寸画布：保持长宽比，不拉伸
        canvas = np.zeros((h, w, 3), dtype=vis.dtype)
        y0, x0 = (h - nh) // 2, (w - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = small

        rgb = np.ascontiguousarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.thumb_label.setPixmap(QPixmap.fromImage(qimg))

    def mousePressEvent(self, e):
        self.clicked.emit(self.res)


class HistoryPanel(QGroupBox):
    item_clicked = pyqtSignal(object)
    cleared = pyqtSignal()

    MAX_ITEMS = 200
    # 一行缩略图需要的最小高度：图 + 两行文字 + 左右/上下内边距 + 横向滚动条
    MIN_ROW_H = HistoryItem.THUMB_H + 44

    def __init__(self):
        super().__init__("检测结果历史")
        # 不再写死高度：下面把「至少能完整显示一行」作为滚动区的最小高度，
        # 面板自己的最小高度由布局推导出来。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # ---- 顶部一行：计数 + 清除历史 ----
        self.count_label = QLabel("共 0 条")
        self.btn_clear = QPushButton("清除历史")
        self.btn_clear.setToolTip("清空下方全部历史缩略图")
        self.btn_clear.clicked.connect(self._on_clear_clicked)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.count_label)
        head.addStretch(1)
        head.addWidget(self.btn_clear)

        # ---- 横向滚动的缩略图条 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setMinimumHeight(self.MIN_ROW_H)

        self.container = QWidget()
        self.layout = QHBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.container)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addLayout(head)
        v.addWidget(self.scroll, 1)

    # ---------- 数据 ----------
    def add_result(self, res: RecognitionResult):
        item = HistoryItem(res)
        item.clicked.connect(self.item_clicked.emit)
        self.layout.addWidget(item)

        # 限制数量
        while self.layout.count() > self.MAX_ITEMS:
            old = self.layout.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        self._update_count()

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
        self._update_count()

    def _on_clear_clicked(self):
        self.clear()
        self.cleared.emit()

    def _update_count(self):
        self.count_label.setText(f"共 {self.layout.count()} 条")
