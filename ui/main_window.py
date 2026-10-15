from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

from ui.widgets.angle_panel import AnglePanel
from ui.widgets.history_panel import HistoryPanel
from ui.widgets.image_view import ImageView
from ui.widgets.model_panel import ModelPanel
from ui.widgets.result_panel import ResultPanel
from ui.widgets.serial_panel import SerialPanel
from ui.widgets.source_panel import SourcePanel


class MainWindow(QMainWindow):
    def __init__(self, controller, config: dict):
        super().__init__()
        self.controller = controller
        self.config = config
        self.setWindowTitle("OCR 识别系统 v2.0")
        self.resize(1400, 900)

        # ---- 左侧：图像显示 ----
        self.image_view = ImageView()
        self.image_view.setMinimumSize(640, 480)

        # ---- 右侧：控制面板 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.model_panel = ModelPanel(
            rec_options=config["models"]["rec_options"],
            ori_options=config["models"]["ori_options"],
            default_rec=config["models"]["default_rec"],
            default_ori=config["models"]["default_ori"],
        )
        self.source_panel = SourcePanel()
        self.angle_panel = AnglePanel(config["recognizer"]["angles"])
        self.result_panel = ResultPanel()
        self.serial_panel = SerialPanel()

        right_layout.addWidget(self.model_panel)
        right_layout.addWidget(self.source_panel)
        right_layout.addWidget(self.angle_panel)
        right_layout.addWidget(self.result_panel)
        right_layout.addWidget(self.serial_panel)
        right_layout.addStretch()

        # ---- 主分割器 ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.image_view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # ---- 底部：历史缩略图 ----
        self.history_panel = HistoryPanel()

        central = QWidget()
        v = QVBoxLayout(central)
        v.addWidget(splitter, 1)
        v.addWidget(self.history_panel, 0)
        self.setCentralWidget(central)

        # ---- 状态栏 ----
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._stats = {"total": 0, "hit": 0, "sum_ms": 0.0}
        self._update_status()

        # ---- 信号连接 ----
        self._connect_signals()

        # ---- 启动时自动刷新串口列表 ----
        QTimer.singleShot(0, self._on_refresh_ports)

    def _connect_signals(self):
        # 模型面板
        self.model_panel.load_requested.connect(self.controller.load_models)

        # 输入源
        self.source_panel.start_requested.connect(self.controller.start_source)
        self.source_panel.stop_requested.connect(self.controller.stop_source)

        # 角度
        self.angle_panel.angles_changed.connect(self.controller.set_angles)

        # 串口
        self.serial_panel.refresh_requested.connect(self._on_refresh_ports)
        self.serial_panel.open_requested.connect(self._on_open_serial)
        self.serial_panel.close_requested.connect(self._on_close_serial)
        self.serial_panel.chk_on_change.stateChanged.connect(
            lambda s: self.controller.set_send_on_change_only(bool(s)))

        # 控制器 → UI
        self.controller.engine_status.connect(self.model_panel.set_loaded)
        self.controller.frame_ready.connect(self.image_view.set_frame)
        self.controller.result_ready.connect(self._on_result)
        self.controller.serial_sent.connect(self._on_serial_sent)
        self.controller.source_finished.connect(self.source_panel.set_running_false)

        # 历史项点击 → 主图区回看
        self.history_panel.item_clicked.connect(self._on_history_clicked)

    def _on_result(self, res):
        self.image_view.set_result(res)
        self.result_panel.update_result(res)
        self.history_panel.add_result(res)

        # 统计
        self._stats["total"] += 1
        self._stats["hit"] += 1 if res.output_value == 1 else 0
        self._stats["sum_ms"] += res.elapsed_ms
        self._update_status(res)

    def _on_serial_sent(self, value: int, ok: bool, msg: str):
        self.serial_panel.update_stats(**self.controller.serial.stats)
        if not ok:
            self.status_bar.showMessage(f"串口发送失败：{msg}", 3000)

    def _on_refresh_ports(self):
        ports = self.controller.refresh_ports()
        self.serial_panel.set_ports(ports)

    def _on_open_serial(self, port: str, baud: int):
        ok, msg = self.controller.open_serial(port, baud)
        self.serial_panel.set_connected(ok, msg)

    def _on_close_serial(self):
        self.controller.close_serial()
        self.serial_panel.set_connected(False, "已关闭")

    def _on_history_clicked(self, res):
        self.image_view.set_result(res, keep_frame=True)

    def _update_status(self, res=None):
        s = self._stats
        avg = (s["sum_ms"] / s["total"]) if s["total"] else 0.0
        parts = [
            f"已处理 {s['total']}",
            f"命中 {s['hit']}",
            f"平均 {avg:.1f}ms",
        ]
        if res is not None:
            parts.append(f"当前 {res.filename or '-'} → {res.output_value}")
        self.status_bar.showMessage("  |  ".join(parts))

    def closeEvent(self, e):
        self.controller.shutdown()
        e.accept()