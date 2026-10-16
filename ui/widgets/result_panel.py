from PyQt6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt

from core.models import RecognitionResult


class ResultPanel(QGroupBox):
    # 判定的显示配色：G=良品(绿) / NG=不良(红) / ?=无法判定(橙) / --=还没跑过(灰)
    _STYLES = {
        "G":  "#2ecc71",
        "NG": "#e74c3c",
        "?":  "#e67e22",
        "--": "#95a5a6",
    }

    def __init__(self):
        super().__init__("检测结果")

        self.number_label = QLabel("--")
        self.number_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedSize(80, 80)
        self._set_value_style("--")

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

    def _set_value_style(self, text: str):
        bg = self._STYLES.get(text, self._STYLES["--"])
        # "NG" 是两个字符，48px 会挤出 80px 的方框，所以按字数收一档
        size = 48 if len(text) <= 1 else 38
        self.value_label.setStyleSheet(
            f"font-size: {size}px; font-weight: bold; color: white;"
            f"background-color: {bg}; border-radius: 8px;")

    def update_result(self, res: RecognitionResult):
        self.number_label.setText(res.number or "--")
        # 显示 G / NG（0→G，1→NG）；识别失败显示 "?"，**不能**显示成绿色的 G
        text = res.output_text
        self.value_label.setText(text)
        self._set_value_style(text)
        self.value_label.setToolTip(
            f"output_value = {res.output_value}（串口按这个原值发送）")
        self.conf_label.setText(
            f"置信度: {res.confidence:.4f}" if res.confidence else "置信度: --")
        self.angle_label.setText(
            f"角度: {res.angle}°" if res.number else "角度: --")
        self.status_label.setText(f"状态: {res.status}")