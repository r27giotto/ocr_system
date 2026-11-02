import os

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QStatusBar, QMessageBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices

from infra.config_writer import ConfigWriteError, set_value

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
        self.source_panel = SourcePanel(config)
        self.angle_panel = AnglePanel(config["recognizer"]["angles"])
        self.result_panel = ResultPanel()
        self.serial_panel = SerialPanel()

        right_layout.addWidget(self.model_panel)
        right_layout.addWidget(self.source_panel)
        right_layout.addWidget(self.angle_panel)
        right_layout.addWidget(self.result_panel)
        right_layout.addWidget(self.serial_panel)
        right_layout.addStretch()

        # 右列包一层滚动区。37 个角度复选框让这一列的「最小高度」涨到 ~890px，
        # 会把竖直分割器的空间全占掉、底部历史区被压到最小且拖不大；
        # 放进滚动区后右列可以被压扁（拥挤时自己出滚动条），历史区才能自由调高。
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 横向条只在「真的被拖得比内容还窄」时出现（正常不会出现）：
        # QScrollArea 自己算出来的最小宽度不含内部控件的要求，会被分割器压到
        # 内容宽以下、把右侧控件裁掉，所以这里显式把它顶到内容的实际最小宽度。
        right_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setWidget(right)
        right_layout.activate()
        # 再加上竖向滚动条的宽度：否则「内容最小宽」会被滚动条吃掉十几个像素，
        # 结果又冒出一条横向滚动条。
        right_scroll.setMinimumWidth(
            max(360,
                right.minimumSizeHint().width()
                + right_scroll.verticalScrollBar().sizeHint().width()))
        self.right_scroll = right_scroll
        self.right_widget = right

        # ---- 主分割器 ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.image_view)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # ---- 底部：历史缩略图 ----
        # 放进竖直 QSplitter，用户可以直接拖动分隔条调节历史区高度；
        # 但缩略图尺寸是固定的（HistoryItem.THUMB_W/THUMB_H），拉高历史区
        # 只会露出更多滚动区，不会把图片放大。
        self.history_panel = HistoryPanel(
            int((config.get("history", {}) or {}).get("max_items", 200) or 200))

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.addWidget(splitter)
        self.v_splitter.addWidget(self.history_panel)
        self.v_splitter.setStretchFactor(0, 4)
        self.v_splitter.setStretchFactor(1, 1)
        self.v_splitter.setCollapsible(0, False)
        self.v_splitter.setCollapsible(1, False)
        # 历史区最小高度由布局推导（实测约 221px），这里给它一个略大的初值
        self.v_splitter.setSizes([640, 230])
        self.setCentralWidget(self.v_splitter)

        # ---- 状态栏 ----
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._stats = {"total": 0, "hit": 0, "sum_ms": 0.0}
        self._update_status()

        # ---- 窗口最小高度 ----
        # 「不被压缩」的基准是图像显示区的最小尺寸（上面 image_view 的 640×480）。
        # 折叠面板只应该把垂直空间**让出来**，不该让窗口跟着缩到显示区被压扁；
        # 所以下限按「图像区最小 + 历史区最小 + 状态栏 + 分隔条」算，
        # 与面板折叠/展开无关。改这几个量前先想清楚——它决定窗口能缩到多小。
        self.setMinimumHeight(
            self.image_view.minimumHeight()
            + self.history_panel.minimumSizeHint().height()
            + self.status_bar.sizeHint().height()
            + 16
        )

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
        # 相机：测试 / 打开原图目录 / 保存张数写回
        self.source_panel.test_requested.connect(
            lambda: self.controller.test_camera())
        self.source_panel.open_dir_requested.connect(self._on_open_dir)
        self.source_panel.max_saved_changed.connect(self._on_max_saved_changed)
        self.controller.preview_ready.connect(self._on_preview)
        self.controller.camera_status.connect(self.source_panel.set_camera_status)

        # 角度
        self.angle_panel.angles_changed.connect(self.controller.set_angles)

        # 串口
        self.serial_panel.refresh_requested.connect(self._on_refresh_ports)
        self.serial_panel.open_requested.connect(self._on_open_serial)
        self.serial_panel.close_requested.connect(self._on_close_serial)

        # 控制器 → UI
        self.controller.engine_status.connect(self.model_panel.set_loaded)
        self.controller.engine_progress.connect(self.model_panel.set_progress)
        # 加载中禁用「开始」：加载线程持着 EngineManager 的锁，
        # 这时开跑会把推理线程堵在加载器后面。
        self.controller.engine_busy.connect(self.source_panel.set_engine_busy)
        self.controller.frame_ready.connect(self.image_view.set_frame)
        self.controller.result_ready.connect(self._on_result)
        self.controller.serial_sent.connect(self._on_serial_sent)
        # 按钮状态只跟 controller.source_state 走：自然跑完、手动停止、
        # 空文件夹、启动失败四条路径都会把它置回 False。
        self.controller.source_state.connect(self.source_panel.set_running)
        self.controller.source_error.connect(self._on_source_error)
        # 非阻断提示（本次运行的 CSV 落在哪 / 写失败）只写状态栏
        self.controller.notice.connect(
            lambda msg: self.status_bar.showMessage(msg, 8000))

        # 历史区在竖直分割器里，折叠不会自己变矮（分割器给的是固定份额），
        # 所以折叠 / 展开时手动把高度让出去 / 还回来。
        self.history_panel.collapsed_changed.connect(self._on_history_collapsed)

        # 历史项点击 → 主图区回看
        self.history_panel.item_clicked.connect(self._on_history_clicked)

        # 清除历史
        self.history_panel.cleared.connect(self._on_history_cleared)

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

    def _on_source_error(self, msg: str):
        """输入源起不来（路径不存在 / 摄像头打不开 / 没测就开拍）。按钮已由
        controller.source_state 复位，这里负责把原因说给用户看。

        相机相关错误用弹窗，因为这往往是「线没插 / 没点测试」这类必须先解决的
        问题，只写状态栏容易被忽略；文件路径错误继续只写状态栏。
        """
        self.status_bar.showMessage(f"启动输入源失败：{msg}", 10000)
        if self.source_panel.rb_camera.isChecked():
            QMessageBox.warning(self, "摄像头", msg)

    # ---------- 相机 ----------
    def _on_preview(self, frame):
        """「测试摄像头」的预览帧：只显示，不参与识别。"""
        self.image_view.set_frame(frame, "预览")

    def _project_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _on_open_dir(self, path: str):
        """打开落盘目录（原图历史 / 识别历史）。目录不存在就先建出来。"""
        full = path if os.path.isabs(path) else os.path.join(self._project_root(), path)
        try:
            os.makedirs(full, exist_ok=True)
        except OSError as e:
            self.status_bar.showMessage(f"目录无法创建：{e}", 5000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(full))

    def _on_max_saved_changed(self, value: int):
        """「保存张数」变了：立刻生效，并写回 config.yaml（下次打开还在）。"""
        self.config.setdefault("camera", {})["max_saved_images"] = int(value)
        store = getattr(self.controller, "capture_store", None)
        if store is not None:
            store.max_images = max(1, int(value))
            store.prune()
        cfg_path = os.path.join(self._project_root(), "config.yaml")
        if not os.path.isfile(cfg_path):
            return
        try:
            set_value(cfg_path, "camera.max_saved_images", int(value))
            self.status_bar.showMessage(f"保存张数已改为 {value}，并写入 config.yaml", 3000)
        except ConfigWriteError as e:
            self.status_bar.showMessage(f"保存张数已生效，但写回配置失败：{e}", 6000)

    def _on_open_serial(self, port: str, baud: int):
        ok, msg = self.controller.open_serial(port, baud)
        self.serial_panel.set_connected(ok, msg)

    def _on_close_serial(self):
        self.controller.close_serial()
        self.serial_panel.set_connected(False, "已关闭")

    def _on_history_clicked(self, res):
        self.image_view.set_result(res, keep_frame=True)

    def _on_history_collapsed(self, collapsed: bool):
        """历史区折叠时把竖直分割器里的高度让给上图区。

        它在 `QSplitter` 里，单纯隐藏正文并不会让它变矮（分割器按份额分配），
        所以要显式改份额；同时用 `setMaximumHeight` 钉住折叠态，免得用户拖动
        分隔条时把一条只有标题的空面板拉高。
        """
        total = max(1, sum(self.v_splitter.sizes()))
        title_h = max(24, self.history_panel.lbl_title.height() + 24)
        if collapsed:
            self._history_h = max(title_h + 40, self.history_panel.height())
            self.history_panel.setMaximumHeight(title_h)
            self.v_splitter.setSizes([total - title_h, title_h])
        else:
            self.history_panel.setMaximumHeight(16777215)
            h = max(title_h + 40, getattr(self, "_history_h", 230))
            self.v_splitter.setSizes([total - h, h])

    def _on_history_cleared(self):
        """清除历史时，把状态栏的累计统计一起归零（否则空历史配着
        「已处理 128」看起来像 bug）。串口已发送/错误计数不在这里，
        它属于串口面板自己的统计。"""
        self._stats = {"total": 0, "hit": 0, "sum_ms": 0.0}
        self._update_status()

    def _update_status(self, res=None):
        s = self._stats
        avg = (s["sum_ms"] / s["total"]) if s["total"] else 0.0
        parts = [
            f"已处理 {s['total']}",
            f"命中 {s['hit']}",
            f"平均 {avg:.1f}ms",
            # 收到的帧 - 已出的结果：停在 0/1 说明没有积压，
            # 一直往上涨就说明有帧没被处理（这一版应该恒为 0/1）
            f"待处理 {self.controller.pending}",
        ]
        if res is not None:
            # 显示 G / NG（与 ResultPanel、历史面板、图像叠层一致）
            parts.append(f"当前 {res.filename or '-'} → {res.output_text}")
        self.status_bar.showMessage("  |  ".join(parts))

    def closeEvent(self, e):
        self.controller.shutdown()
        e.accept()