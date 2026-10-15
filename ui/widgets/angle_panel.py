from PyQt6.QtWidgets import (
    QGroupBox, QCheckBox, QPushButton, QGridLayout, QHBoxLayout, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal


class AnglePanel(QGroupBox):
    angles_changed = pyqtSignal(list)

    # 每 10 度一个，覆盖 -180° ~ 180°（共 37 个）
    ALL_ANGLES = list(range(-180, 181, 10))
    # 4 列：右侧控制列大约 360~400px 宽，5 列会把最后一列挤出可视区
    COLUMNS = 4

    # 默认勾选：原方案那一批，取值都落在 10 度网格上
    DEFAULT_ANGLES = [-90, -60, -30, 0, 30, 60, 90, 180]

    def __init__(self, default_checked=None):
        super().__init__("角度选择")
        if default_checked is None:
            default_checked = self.DEFAULT_ANGLES
        # config.yaml 里若写了不在网格上的角度（例如旧的 -45 / 45），这里直接丢掉，
        # 否则会出现「识别器用了 37 个角度，面板却只勾了 8 个」的不一致。
        dropped = [a for a in default_checked if a not in self.ALL_ANGLES]
        if dropped:
            print(f"[AnglePanel] 配置里的角度不在 10 度网格上，已忽略: {dropped}")
        default_checked = set(default_checked) & set(self.ALL_ANGLES)

        self.checkboxes: dict[int, QCheckBox] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        for i, ang in enumerate(self.ALL_ANGLES):
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in default_checked)
            cb.stateChanged.connect(self._emit)
            grid.addWidget(cb, i // self.COLUMNS, i % self.COLUMNS)
            self.checkboxes[ang] = cb

        btn_all = QPushButton("全选")
        btn_zero = QPushButton("仅 0°")
        btn_inv = QPushButton("反选")
        btn_default = QPushButton("默认")
        btn_all.setToolTip("勾选全部 37 个角度（很慢）")
        btn_zero.setToolTip("只保留 0°")
        btn_inv.setToolTip("已勾选的取消，未勾选的勾上")
        btn_default.setToolTip("恢复默认勾选")
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
        v.addLayout(btn_row)

    def selected_angles(self) -> list[int]:
        return [a for a, cb in self.checkboxes.items() if cb.isChecked()]

    def _emit(self):
        self.angles_changed.emit(self.selected_angles())

    def _apply_bulk(self, chooser):
        """批量改动：先屏蔽单个复选框的信号，最后只发一次 angles_changed。
        否则「全选」会连续发 37 次信号、触发 37 次 set_angles。"""
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
        self._apply_bulk(lambda a: a in keep)
