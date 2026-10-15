from PyQt6.QtWidgets import (
    QGroupBox, QCheckBox, QPushButton, QGridLayout, QHBoxLayout, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal


class AnglePanel(QGroupBox):
    """角度选择。

    界面只列 0°~180°（每 10 度一个，共 19 个）；负角度不单独占格子，由
    「负号」复选框统一控制：勾上时每个勾选角度会连带尝试它的相反数。
    常见的「正负都要试」一次点击就能切换，界面也不必塞 37 个复选框。
    """

    angles_changed = pyqtSignal(list)

    # 每 10 度一个，0° ~ 180°（共 19 个）
    POSITIVE_ANGLES = list(range(0, 181, 10))
    COLUMNS = 4

    # 默认勾选 0/30/60/90/180 并且带负号 ——
    # 展开后正好等于原来的 [-90,-60,-30,0,30,60,90,180]
    DEFAULT_ANGLES = [0, 30, 60, 90, 180]
    DEFAULT_NEGATIVE = True

    def __init__(self, default_checked=None):
        super().__init__("角度选择")

        # ---- 从 config.yaml 推导初始勾选状态 ----
        if default_checked is None:
            checked = list(self.DEFAULT_ANGLES)
            negative = self.DEFAULT_NEGATIVE
        else:
            vals = [int(a) for a in default_checked]
            # 配置里出现了负数 → 负号默认勾上；负号本身不占独立的格子
            negative = any(v < 0 for v in vals)
            checked = [abs(v) for v in vals]

        off_grid = sorted({a for a in checked if a not in self.POSITIVE_ANGLES})
        if off_grid:
            print("[AnglePanel] 配置里的角度不在 0~180 每 10 度的网格上，"
                  f"已忽略: {off_grid}")
        checked_set = set(checked) & set(self.POSITIVE_ANGLES)

        # ---- 19 个角度复选框 ----
        self.checkboxes: dict[int, QCheckBox] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        for i, ang in enumerate(self.POSITIVE_ANGLES):
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in checked_set)
            cb.stateChanged.connect(self._emit)
            grid.addWidget(cb, i // self.COLUMNS, i % self.COLUMNS)
            self.checkboxes[ang] = cb

        # ---- 负号开关 ----
        self.cb_negative = QCheckBox("负号（每个勾选角度同时尝试 -θ）")
        self.cb_negative.setChecked(bool(negative))
        self.cb_negative.setToolTip(
            "勾上：勾了 30° 就同时尝试 +30° 和 -30°\n"
            "不勾：只用正值角度\n"
            "0° 没有正负之分；180° 与 -180° 是同一次旋转，会自动合并成一个")
        self.cb_negative.stateChanged.connect(self._emit)

        # ---- 批量按钮 ----
        btn_all = QPushButton("全选")
        btn_zero = QPushButton("仅 0°")
        btn_inv = QPushButton("反选")
        btn_default = QPushButton("默认")
        btn_all.setToolTip("勾选全部 19 个角度（很慢）")
        btn_zero.setToolTip("只保留 0°")
        btn_inv.setToolTip("已勾选的取消，未勾选的勾上")
        btn_default.setToolTip("恢复默认勾选和负号状态")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_zero.clicked.connect(self._set_zero_only)
        btn_inv.clicked.connect(self._invert)
        btn_default.clicked.connect(self._set_default)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        for b in (btn_all, btn_zero, btn_inv, btn_default):
            btn_row.addWidget(b)
        btn_row.addStretch()

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)
        v.addLayout(grid)
        v.addWidget(self.cb_negative)
        v.addLayout(btn_row)

    # ---------- 对外状态 ----------
    @property
    def negative_enabled(self) -> bool:
        return self.cb_negative.isChecked()

    def selected_angles(self) -> list[int]:
        """真正要送给识别器的角度列表。

        勾选的「正值」在这里展开成 ± 两个角度（受负号开关控制），并按 |角度|
        升序排列 —— 和 Recognizer.set_angles 里的排序一致，0° 排最前。
        """
        pos = [a for a, cb in self.checkboxes.items() if cb.isChecked()]
        if not self.cb_negative.isChecked():
            return sorted(pos, key=lambda a: (abs(a), a))

        out = set()
        for a in pos:
            out.add(a)
            if a != 0:
                out.add(-a)
            if a == 180:
                out.discard(-180)      # -180° 与 180° 是同一次旋转，合并掉
        return sorted(out, key=lambda a: (abs(a), a))

    # ---------- 内部 ----------
    def _emit(self):
        self.angles_changed.emit(self.selected_angles())

    def _apply_bulk(self, chooser):
        """批量改动：先屏蔽单个复选框的信号，最后只发一次 angles_changed。
        否则「全选」会连续发 19 次信号、触发 19 次 set_angles。"""
        for a, cb in self.checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(bool(chooser(a)))
            cb.blockSignals(False)
        self._emit()

    def _set_all(self, checked: bool):
        self._apply_bulk(lambda a: checked)

    def _set_zero_only(self):
        self._apply_bulk(lambda a: a == 0)

    def _invert(self):
        self._apply_bulk(lambda a: not self.checkboxes[a].isChecked())

    def _set_default(self):
        keep = set(self.DEFAULT_ANGLES)
        self.cb_negative.blockSignals(True)
        self.cb_negative.setChecked(self.DEFAULT_NEGATIVE)
        self.cb_negative.blockSignals(False)
        self._apply_bulk(lambda a: a in keep)
