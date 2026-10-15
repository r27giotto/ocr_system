from PyQt6.QtWidgets import (
    QGroupBox, QCheckBox, QPushButton, QGridLayout, QHBoxLayout, QVBoxLayout, QLabel
)
from PyQt6.QtCore import pyqtSignal


class AnglePanel(QGroupBox):
    """角度选择。

    角度分成两组：

    · **固定角度 0° / 180°** —— 没有正负之分（-0° 就是 0°，-180° 与 180°
      是同一次旋转），所以单独占一行，**不受「负号」开关影响**。
    · **旋转角度 10°~170°**（每 10 度一个，共 17 个）—— 由「负号」开关统一
      控制：勾上时每个勾选角度连带尝试它的相反数。

    这样界面不必塞 37 个复选框（0~180 与 -180~-10 各一份），
    常见的「正负都要试」一次点击就能切换。
    """

    angles_changed = pyqtSignal(list)

    # 没有正负之分的两个角度
    FIXED_ANGLES = (0, 180)
    # 需要正负切换的旋转角度
    ROTATION_ANGLES = list(range(10, 180, 10))      # 17 个
    COLUMNS = 4

    # 默认：固定角度全要；旋转角度 30/60/90 带负号。
    # 展开 = [0, 180, -30, 30, -60, 60, -90, 90]，与旧版默认完全一致。
    DEFAULT_FIXED = (0, 180)
    DEFAULT_ROTATION = (30, 60, 90)
    DEFAULT_NEGATIVE = True

    def __init__(self, default_checked=None):
        super().__init__("角度选择")

        # ---- 从 config.yaml 推导初始勾选状态 ----
        if default_checked is None:
            fixed = list(self.DEFAULT_FIXED)
            rot = list(self.DEFAULT_ROTATION)
            negative = self.DEFAULT_NEGATIVE
        else:
            vals = [int(a) for a in default_checked]
            # 配置里出现了负数 → 负号默认勾上；负号本身不占独立的格子
            negative = any(v < 0 for v in vals)
            absv = [abs(v) for v in vals]
            valid = set(self.FIXED_ANGLES) | set(self.ROTATION_ANGLES)
            off_grid = sorted({a for a in absv if a not in valid})
            if off_grid:
                print("[AnglePanel] 配置里的角度不在 0~180 每 10 度的网格上，"
                      f"已忽略: {off_grid}")
            fixed = sorted({a for a in absv if a in self.FIXED_ANGLES})
            rot = sorted({a for a in absv if a in self.ROTATION_ANGLES})

        # ---- 固定角度行：0° / 180° ----
        self.fixed_boxes: dict[int, QCheckBox] = {}
        fixed_row = QHBoxLayout()
        fixed_row.setContentsMargins(0, 0, 0, 0)
        fixed_row.setSpacing(6)
        lbl_fixed = QLabel("固定角度（无 ±）:")
        lbl_fixed.setToolTip(
            "0° 和 180° 没有正负之分：\n"
            "-0° 就是 0°；-180° 与 180° 是同一次旋转。\n"
            "所以它们不受下面「负号」开关影响。")
        fixed_row.addWidget(lbl_fixed)
        for ang in self.FIXED_ANGLES:
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in fixed)
            cb.setToolTip(f"{ang}° 无正负之分，不受「负号」影响")
            cb.stateChanged.connect(self._emit)
            fixed_row.addWidget(cb)
            self.fixed_boxes[ang] = cb
        fixed_row.addStretch()

        # ---- 旋转角度网格：10° ~ 170° ----
        self.checkboxes: dict[int, QCheckBox] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        for i, ang in enumerate(self.ROTATION_ANGLES):
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in rot)
            cb.stateChanged.connect(self._emit)
            grid.addWidget(cb, i // self.COLUMNS, i % self.COLUMNS)
            self.checkboxes[ang] = cb

        # ---- 负号开关（只作用于旋转角度）----
        self.cb_negative = QCheckBox("负号（10°~170° 每个勾选角度同时尝试 -θ）")
        self.cb_negative.setChecked(bool(negative))
        self.cb_negative.setToolTip(
            "勾上：勾了 30° 就同时尝试 +30° 和 -30°\n"
            "不勾：旋转角度只用正值\n"
            "上面的 0° / 180° 无正负之分，不受这里影响")
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
        v.addLayout(fixed_row)
        v.addLayout(grid)
        v.addWidget(self.cb_negative)
        v.addLayout(btn_row)

    # ---------- 对外状态 ----------
    @property
    def negative_enabled(self) -> bool:
        return self.cb_negative.isChecked()

    def total_angles(self) -> int:
        """面板上一共有多少个复选框。"""
        return len(self.fixed_boxes) + len(self.checkboxes)

    def selected_angles(self) -> list[int]:
        """真正要送给识别器的角度列表。

        固定角度（0°/180°）按勾选原样加入；旋转角度在负号勾上时展开成 ±。
        因为 ROTATION_ANGLES 里没有 0/180，-a 永远不会和固定角度撞车，
        所以这里不需要任何特例。最后按 |角度| 升序排 —— 和
        Recognizer.set_angles 的排序一致，0° 排最前。
        """
        out = {a for a, cb in self.fixed_boxes.items() if cb.isChecked()}
        rot = [a for a, cb in self.checkboxes.items() if cb.isChecked()]
        if self.cb_negative.isChecked():
            for a in rot:
                out.add(a)
                out.add(-a)
        else:
            out.update(rot)
        return sorted(out, key=lambda a: (abs(a), a))

    # ---------- 内部 ----------
    def _all_boxes(self) -> dict[int, QCheckBox]:
        return {**self.fixed_boxes, **self.checkboxes}

    def _emit(self):
        self.angles_changed.emit(self.selected_angles())

    def _apply_bulk(self, chooser):
        """批量改动：先屏蔽单个复选框的信号，最后只发一次 angles_changed。
        否则「全选」会连续发 19 次信号、触发 19 次 set_angles。"""
        for a, cb in self._all_boxes().items():
            cb.blockSignals(True)
            cb.setChecked(bool(chooser(a)))
            cb.blockSignals(False)
        self._emit()

    def _set_all(self, checked: bool):
        self._apply_bulk(lambda a: checked)

    def _set_zero_only(self):
        self._apply_bulk(lambda a: a == 0)

    def _invert(self):
        boxes = self._all_boxes()
        self._apply_bulk(lambda a: not boxes[a].isChecked())

    def _set_default(self):
        keep_fixed = set(self.DEFAULT_FIXED)
        keep_rot = set(self.DEFAULT_ROTATION)
        self.cb_negative.blockSignals(True)
        self.cb_negative.setChecked(self.DEFAULT_NEGATIVE)
        self.cb_negative.blockSignals(False)
        self._apply_bulk(
            lambda a: a in keep_fixed if a in self.fixed_boxes else a in keep_rot)
