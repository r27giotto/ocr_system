from PyQt6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt

from core.models import RecognitionResult


class ResultPanel(QGroupBox):
    def __init__(self):
        super().__init__("检测结果")

        self.number_label = QLabel("--")
        self.number_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedSize(80, 80)
        self._set_value_style(0)

        self.conf_label = QLabel("置信度: --")
        self.angle_label = QLabel("角度: --")
        self.status_label = QLabel("状态: 等待")

        value_row = QHBoxLayout()
        value_row.addStretch()
        value_row.addWidget(self.value_label)
        value_row.addStretch()

        v = QVBoxLayout(self)
        v.addWidget(QLabel("识别数字:"))
        v.addWidget(self.number_label)
        v.addLayout(value_row)
        v.addWidget(self.conf_label)
        v.addWidget(self.angle_label)
        v.addWidget(self.status_label)

    def _set_value_style(self, value: int):
        if value == 1:
            self.value_label.setStyleSheet(
                "font-size: 48px; font-weight: bold; color: white;"
                "background-color: #2ecc71; border-radius: 8px;")
        else:
            self.value_label.setStyleSheet(
                "font-size: 48px; font-weight: bold; color: white;"
                "background-color: #95a5a6; border-radius: 8px;")

    def update_result(self, res: RecognitionResult):
        self.number_label.setText(res.number or "--")
        self.value_label.setText(str(res.output_value))
        self._set_value_style(res.output_value)
        self.conf_label.setText(
            f"置信度: {res.confidence:.4f}" if res.confidence else "置信度: --")
        self.angle_label.setText(
            f"角度: {res.angle}°" if res.number else "角度: --")
        self.status_label.setText(f"状态: {res.status}")