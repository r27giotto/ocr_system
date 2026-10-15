from PyQt6.QtWidgets import (
    QGroupBox, QCheckBox, QPushButton, QGridLayout, QHBoxLayout, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal


class AnglePanel(QGroupBox):
    angles_changed = pyqtSignal(list)

    ALL_ANGLES = [-90, -60, -45, -30, 0, 30, 45, 60, 90, 180]

    def __init__(self, default_checked=None):
        super().__init__("角度选择")
        if default_checked is None:
            default_checked = self.ALL_ANGLES

        self.checkboxes: dict[int, QCheckBox] = {}
        grid = QGridLayout()
        for i, ang in enumerate(self.ALL_ANGLES):
            cb = QCheckBox(f"{ang}°")
            cb.setChecked(ang in default_checked)
            cb.stateChanged.connect(self._emit)
            grid.addWidget(cb, i // 5, i % 5)
            self.checkboxes[ang] = cb

        btn_all = QPushButton("全选")
        btn_zero = QPushButton("仅 0°")
        btn_inv = QPushButton("反选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_zero.clicked.connect(self._set_zero_only)
        btn_inv.clicked.connect(self._invert)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_zero)
        btn_row.addWidget(btn_inv)
        btn_row.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(grid)
        v.addLayout(btn_row)

    def selected_angles(self) -> list[int]:
        return [a for a, cb in self.checkboxes.items() if cb.isChecked()]

    def _emit(self):
        self.angles_changed.emit(self.selected_angles())

    def _set_all(self, checked: bool):
        for cb in self.checkboxes.values():
            cb.setChecked(checked)

    def _set_zero_only(self):
        for a, cb in self.checkboxes.items():
            cb.setChecked(a == 0)

    def _invert(self):
        for cb in self.checkboxes.values():
            cb.setChecked(not cb.isChecked())