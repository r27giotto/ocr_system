from PyQt6.QtWidgets import (
    QGroupBox, QComboBox, QPushButton, QLabel, QFormLayout, QHBoxLayout, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal


class ModelPanel(QGroupBox):
    load_requested = pyqtSignal(str, str)   # (rec_name, ori_name)

    def __init__(self, rec_options, ori_options, default_rec, default_ori):
        super().__init__("模型选择")

        self.rec_combo = QComboBox()
        self.rec_combo.addItems(rec_options)
        self.rec_combo.setCurrentText(default_rec)

        self.ori_combo = QComboBox()
        self.ori_combo.addItems(ori_options)
        self.ori_combo.setCurrentText(default_ori)

        self.btn_load = QPushButton("加载模型")
        self.btn_load.clicked.connect(self._on_load)

        self.status_label = QLabel("● 未加载")
        self.status_label.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("识别模型:", self.rec_combo)
        form.addRow("方向模型:", self.ori_combo)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_load)
        bottom.addWidget(self.status_label)
        bottom.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addLayout(bottom)

    def _on_load(self):
        self.btn_load.setEnabled(False)
        self.status_label.setText("● 加载中…")
        self.status_label.setStyleSheet("color: orange;")
        self.load_requested.emit(
            self.rec_combo.currentText(),
            self.ori_combo.currentText(),
        )

    def set_loaded(self, ok: bool, msg: str = ""):
        self.btn_load.setEnabled(True)
        if ok:
            self.status_label.setText("● 已加载")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText(f"● 加载失败: {msg[:30]}")
            self.status_label.setStyleSheet("color: red;")