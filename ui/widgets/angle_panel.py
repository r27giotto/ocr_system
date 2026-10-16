from PyQt6.QtWidgets import (
    QGroupBox, QCheckBox, QComboBox, QPushButton, QGridLayout, QHBoxLayout,
    QVBoxLayout, QLabel
)
from PyQt6.QtCore import pyqtSignal


class AnglePanel(QGroupBox):
    """角度选择。

    角度分成两组：

    · **固定角度 0° / 180°** —— 没有正负之分（-0° 就是 0°，-180° 与 180°
      是同一次旋转），所以单独占一行，**不受「负号」开关影响**。
    · **旋转角度** —— 范围随步长而定，默认 5° ~ 175°（每 5 度一个，共 35 个）。
      步长由上面的下拉框选择：5 / 10 / 15 / 20 / 30 度，也就是把 180° 分成
      36 / 18 / 12 / 9 / 6 等分。由「负号」开关统一控制：勾上时每个勾选角度
      连带尝试它的相反数（0° 和 180° 除外）。

    这样界面不必把 0~180 与 -180~-10 各列一份（最多 71 个复选框），
    常见的「正负都要试」一次点击就能切换。
    """

    angles_changed = pyqtSignal(list)

    # 没有正负之分的两个角度
    FIXED_ANGLES = (0, 180)
    # 旋转角度的可选步长（度）
    STEP_OPTIONS = (5, 10, 15, 20, 30)
    DEFAULT_STEP = 5
    COLUMNS = 5

    # 默认：固定角度全要；旋转角度 30/60/90 带负号。
    # 展开 = [0, 180, -30, 30, -60, 60, -90, 90]。
    DEFAULT_FIXED = (0, 180)
    DEFAULT_ROTATION = (30, 60, 90)
    DEFAULT_NEGATIVE = True

    @staticmethod
    def rotation_angles(step: int) -> list[int]:
        """某一个步长下的旋转角度网格。

        0° 和 180° 归固定行，所以这里严格取 (0, 180) 之间的格点：
        step, 2*step, … 直到小于 180。
        """
        step = max(1, int(step))
        return list(range(step, 180, step))

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
            # 以最细的网格（默认步长）为合法集合：能表示 = 是它的整数倍
            valid = set(self.FIXED_ANGLES) | set(self.rotation_angles(self.DEFAULT_STEP))
            off_grid = sorted({a for a in absv if a not in valid})
            if off_grid:
                print("[AnglePanel] 配置里的角度不在固定角度 ∪ "
                      f"0~180 每 {self.DEFAULT_STEP} 度的网格上，已忽略: {off_grid}")
            fixed = sorted({a for a in absv if a in self.FIXED_ANGLES})
            rot = sorted({a for a in absv
                          if a not in self.FIXED_ANGLES
                          and a in self.rotation_angles(self.DEFAULT_STEP)})

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

        # ---- 步长下拉框 ----
        self.combo_step = QComboBox()
        for s in self.STEP_OPTIONS:
            self.combo_step.addItem(f"步长 {s}°（180 ÷ {s} = {180 // s} 等分）", s)
        self.combo_step.setCurrentIndex(self.STEP_OPTIONS.index(self.DEFAULT_STEP))
        self.combo_step.setToolTip(
            "旋转角度网格的疏密。步长越小越细、要试的角度越多、越慢。\n"
            "0° 和 180° 始终在固定角度行，不随步长变化。")
        # 先设好初始项再连信号，避免构造期就触发重建
        self.combo_step.currentIndexChanged.connect(self._on_step_changed)

        step_row = QHBoxLayout()
        step_row.setContentsMargins(0, 0, 0, 0)
        step_row.setSpacing(6)
        step_row.addWidget(QLabel("旋转角度步长:"))
        step_row.addWidget(self.combo_step)
        step_row.addStretch()

        # ---- 负号开关（只作用于旋转角度）----
        self.cb_negative = QCheckBox("负号")
        self.cb_negative.setChecked(bool(negative))
        self.cb_negative.setToolTip(
            "勾上：勾了 30° 就同时尝试 +30° 和 -30°\n"
            "不勾：旋转角度只用正值\n"
            "上面的 0° / 180° 无正负之分，不受这里影响")
        self.cb_negative.stateChanged.connect(self._emit)

        # ---- 批量按钮 ----
        self.btn_all = QPushButton("全选")
        btn_zero = QPushButton("仅 0°")
        btn_inv = QPushButton("反选")
        btn_default = QPushButton("默认")
        self.btn_all.setToolTip("勾选全部旋转角度（越细越慢）")
        btn_zero.setToolTip("只保留 0°")
        btn_inv.setToolTip("已勾选的取消，未勾选的勾上")
        btn_default.setToolTip(
            "恢复默认勾选（0/180 与 30/60/90）和负号状态；\n步长保持不变")
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        btn_zero.clicked.connect(self._set_zero_only)
        btn_inv.clicked.connect(self._invert)
        btn_default.clicked.connect(self._set_default)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        for b in (self.btn_all, btn_zero, btn_inv, btn_default):
            btn_row.addWidget(b)
        btn_row.addStretch()

        # ---- 旋转角度网格（按当前步长生成）----
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(1)
        self.checkboxes: dict[int, QCheckBox] = {}
        self._step = self.DEFAULT_STEP
        self._rebuild_grid(self.DEFAULT_STEP, keep=set(rot))

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)
        v.addLayout(fixed_row)
        v.addLayout(step_row)
        v.addLayout(self.grid)
        v.addWidget(self.cb_negative)
        v.addLayout(btn_row)

    # ---------- 对外状态 ----------
    @property
    def step(self) -> int:
        """当前步长（度）。"""
        return self._step

    @property
    def negative_enabled(self) -> bool:
        return self.cb_negative.isChecked()

    def total_angles(self) -> int:
        """面板上一共有多少个复选框。"""
        return len(self.fixed_boxes) + len(self.checkboxes)

    def selected_angles(self) -> list[int]:
        """真正要送给识别器的角度列表。

        固定角度（0°/180°）按勾选原样加入；旋转角度在负号勾上时展开成 ±。
        旋转网格里不含 0/180，-a 永远不会和固定角度撞车，所以这里不需要
        任何特例。最后按 |角度| 升序排 —— 和 Recognizer.set_angles 的
        排序一致，0° 排最前。
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
    def _rebuild_grid(self, step: int, keep=None):
        """按步长重建旋转角度网格，keep 里的角度若还在新网格上就保持勾选。"""
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.checkboxes.clear()
        self._step = step
        keep = set() if keep is None else set(keep)
        for i, ang in enumerate(self.rotation_angles(step)):
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in keep)
            cb.stateChanged.connect(self._emit)
            self.grid.addWidget(cb, i // self.COLUMNS, i % self.COLUMNS)
            self.checkboxes[ang] = cb
        self._sync_labels()

    def _sync_labels(self):
        """跟着网格大小走的文案。"""
        angs = self.rotation_angles(self._step)
        if angs:
            self.cb_negative.setText(
                f"负号（{angs[0]}°~{angs[-1]}° 每个勾选角度同时尝试 -θ）")
        self.btn_all.setToolTip(f"勾选全部 {len(self.checkboxes)} 个旋转角度（越细越慢）")

    def _on_step_changed(self, index: int):
        step = int(self.combo_step.itemData(index))
        if step == self._step:
            return
        before = {a for a, cb in self.checkboxes.items() if cb.isChecked()}
        new_grid = set(self.rotation_angles(step))
        dropped = sorted(before - new_grid)
        self._rebuild_grid(step, keep=before & new_grid)
        if dropped:
            print(f"[AnglePanel] 步长改为 {step}° 后，不在新网格上的角度已取消: {dropped}")
        self._emit()

    def _all_boxes(self) -> dict[int, QCheckBox]:
        return {**self.fixed_boxes, **self.checkboxes}

    def _emit(self):
        self.angles_changed.emit(self.selected_angles())

    def _apply_bulk(self, chooser):
        """批量改动：先屏蔽单个复选框的信号，最后只发一次 angles_changed。
        否则「全选」会连续发几十次信号、触发几十次 set_angles。"""
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
        keep_rot = set(self.DEFAULT_ROTATION) & set(self.checkboxes)
        self.cb_negative.blockSignals(True)
        self.cb_negative.setChecked(self.DEFAULT_NEGATIVE)
        self.cb_negative.blockSignals(False)
        self._apply_bulk(
            lambda a: a in keep_fixed if a in self.fixed_boxes else a in keep_rot)
