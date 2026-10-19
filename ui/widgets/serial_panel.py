from PyQt6.QtWidgets import (
    QGroupBox, QComboBox, QPushButton, QLabel,
    QHBoxLayout, QVBoxLayout, QFormLayout
)
from PyQt6.QtCore import pyqtSignal


class SerialPanel(QGroupBox):
    open_requested = pyqtSignal(str, int)
    close_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, baud_options=(9600, 19200, 38400, 57600, 115200, 230400)):
        super().__init__("串口 (Arduino)")

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems([str(b) for b in baud_options])
        self.baud_combo.setCurrentText("115200")

        self.btn_refresh = QPushButton("刷新")
        self.btn_open = QPushButton("打开串口")
        self.btn_close = QPushButton("关闭串口")
        self.btn_close.setEnabled(False)

        self.status_label = QLabel("● 未连接")
        self.status_label.setStyleSheet("color: gray;")

        self.sent_label = QLabel("已发送: 0")
        self.error_label = QLabel("错误: 0")

        # ★ 不再提供「仅变化时发送」：固件是「收到 '1' 吹一次、收到 '0' 立刻关」，
        #   必须**每张图发一个字节**，才能做到一颗一动作。连续两颗 NG 若只在
        #   变化时发，第二颗就不会吹。
        self.per_frame_label = QLabel("每张图发 1 字节：'1'=NG 吹阀 / '0'=G 放行")
        self.per_frame_label.setStyleSheet("color: #666;")
        self.per_frame_label.setWordWrap(True)

        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_open.clicked.connect(
            lambda: self.open_requested.emit(
                self.port_combo.currentData() or self.port_combo.currentText(),
                int(self.baud_combo.currentText())))
        self.btn_close.clicked.connect(self.close_requested.emit)

        form = QFormLayout()
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.btn_refresh)
        form.addRow("端口:", port_row)
        form.addRow("波特率:", self.baud_combo)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_close)
        btn_row.addStretch()

        stat_row = QHBoxLayout()
        stat_row.addWidget(self.sent_label)
        stat_row.addWidget(self.error_label)
        stat_row.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addLayout(btn_row)
        v.addWidget(self.status_label)
        v.addLayout(stat_row)
        v.addWidget(self.per_frame_label)

    def set_ports(self, ports: list[dict]):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for p in ports:
            self.port_combo.addItem(f"{p['device']} - {p['desc']}", p["device"])
        if current:
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def set_connected(self, ok: bool, msg: str = ""):
        if ok:
            self.status_label.setText(f"● {msg}")
            self.status_label.setStyleSheet("color: green;")
            self.btn_open.setEnabled(False)
            self.btn_close.setEnabled(True)
        else:
            self.status_label.setText(f"● {msg or '未连接'}")
            self.status_label.setStyleSheet(
                "color: red;" if msg else "color: gray;")
            self.btn_open.setEnabled(True)
            self.btn_close.setEnabled(False)

    def update_stats(self, sent: int = 0, errors: int = 0, **kwargs):
        self.sent_label.setText(f"已发送: {sent}")
        self.error_label.setText(f"错误: {errors}")
