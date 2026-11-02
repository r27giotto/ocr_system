# -*- coding: utf-8 -*-
"""可折叠的分组面板基类。

右列被 37 个角度复选框撑得很高，窗口一矮就得靠滚动条。所有控制面板都从这里
继承：**标题行右侧有个 ▾ / ▸ 按钮**，点一下把正文收起来、只留标题条，把垂直
空间让给正在用的面板或图像区。

实现要点：`QGroupBox` 自己的标题是画在边框上的、塞不进按钮，所以这里
`setTitle("")`，改用标题 `QLabel` + 按钮自己排一行；`body_layout()` 返回正文
布局，面板把子控件加进去即可（原来写 `QVBoxLayout(self)` 的地方换成它）。

折叠只是 `body` 隐藏 —— `QVBoxLayout` 会自动把隐藏子控件的尺寸算成 0，
面板自然缩到标题条高度，不需要手工改 minimumHeight。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox, QWidget, QLabel, QToolButton, QHBoxLayout, QVBoxLayout,
)


class CollapsibleGroupBox(QGroupBox):
    """带折叠按钮的分组面板。子类在 `__init__` 里调 `super().__init__(标题)`，
    然后用 `self.body_layout()` 拿正文布局。"""

    collapsed_changed = pyqtSignal(bool)

    # 用 ▼/▶（GB2312 里就有，中文字体必带）而不是 ▾/▸ 这类小三角，
    # 后者在部分字体里会显示成方框。
    ARROW_OPEN = "▼"
    ARROW_CLOSED = "▶"

    def __init__(self, title: str, collapsed: bool = False):
        super().__init__()
        # 标题交给下面的 label 画，QGroupBox 只负责边框
        self.setTitle("")
        self._title_text = title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 7)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self.lbl_title = QLabel(title)
        font = self.lbl_title.font()
        font.setBold(True)
        self.lbl_title.setFont(font)
        self.lbl_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_title.setToolTip("点标题或右侧按钮折叠 / 展开")

        self.btn_collapse = QToolButton()
        self.btn_collapse.setAutoRaise(True)
        self.btn_collapse.setCheckable(True)
        self.btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse.setFixedSize(22, 18)
        self.btn_collapse.setToolTip("折叠 / 展开")

        header.addWidget(self.lbl_title)
        header.addStretch(1)
        header.addWidget(self.btn_collapse)
        outer.addLayout(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(6)
        outer.addWidget(self._body)

        self._collapsed = False
        self.btn_collapse.clicked.connect(self.set_collapsed)
        self.lbl_title.mousePressEvent = self._on_title_clicked  # noqa: SLF001
        self.set_collapsed(collapsed)

    # ---------- 给子类用 ----------
    def body_layout(self) -> QVBoxLayout:
        """正文布局：子控件加到这儿。"""
        return self._body_layout

    def body_widget(self) -> QWidget:
        return self._body

    def title_text(self) -> str:
        return self._title_text

    # ---------- 折叠 ----------
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed and collapsed:
            # 只同步一下控件状态，避免重复发信号
            self.btn_collapse.setChecked(collapsed)
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self.btn_collapse.setText(
            self.ARROW_CLOSED if collapsed else self.ARROW_OPEN)
        self.btn_collapse.setChecked(collapsed)
        self.collapsed_changed.emit(collapsed)

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def _on_title_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_collapsed()
        else:
            QLabel.mousePressEvent(self.lbl_title, event)
