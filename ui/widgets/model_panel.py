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
        self.set_progress()
        self.load_requested.emit(
            self.rec_combo.currentText(),
            self.ori_combo.currentText(),
        )

    def set_progress(self, msg: str = ""):
        """加载过程中的进度提示。

        必须和 set_loaded 分开：加载中 != 失败。以前两者共用
        engine_status(ok=False)，界面会先闪两次红色的「加载失败」。
        这里也**不能**放开按钮，否则加载没结束就能再点一次。
        """
        full = (msg or "").strip()
        brief = full.splitlines()[-1] if full else ""
        self.status_label.setText(f"● 加载中… {brief[:40]}" if brief else "● 加载中…")
        self.status_label.setToolTip(full)
        self.status_label.setStyleSheet("color: orange;")
        self.btn_load.setEnabled(False)

    def set_loaded(self, ok: bool, msg: str = ""):
        self.btn_load.setEnabled(True)
        if ok:
            self.status_label.setText("● 已加载")
            self.status_label.setToolTip("")
            self.status_label.setStyleSheet("color: green;")
        else:
            # 标签只放异常最后一行，完整内容进 tooltip；
            # 原来写 msg[:30] 会把真正的原因截掉，导致只看到「加载失败」。
            full = msg.strip()
            brief = full.splitlines()[-1] if full else "未知错误"
            self.status_label.setText(f"● 加载失败: {brief[:60]}")
            self.status_label.setToolTip(full)
            self.status_label.setStyleSheet("color: red;")