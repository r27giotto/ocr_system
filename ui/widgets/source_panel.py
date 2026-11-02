# -*- coding: utf-8 -*-
"""输入源面板：文件夹 / 单图 / 摄像头（Basler 硬件触发）。"""
from PyQt6.QtWidgets import (
    QGroupBox, QRadioButton, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QFileDialog, QHBoxLayout, QVBoxLayout, QLabel,
    QWidget
)
from PyQt6.QtCore import pyqtSignal


class SourcePanel(QGroupBox):
    start_requested = pyqtSignal(dict)
    stop_requested = pyqtSignal()
    test_requested = pyqtSignal()            # 「测试摄像头」
    open_dir_requested = pyqtSignal(str)     # 「原图历史」：把路径交给上层去打开
    max_saved_changed = pyqtSignal(int)      # 「保存张数」变了，要写回 config.yaml

    def __init__(self, config: dict = None):
        """config 传**整份** `config.yaml`：本面板用到 `source:` / `camera:` /
        `storage:` 三段。界面上的改动不会写回文件，除了「保存张数」——那个由
        上层通过 `max_saved_changed` 落盘。
        """
        super().__init__("输入源")
        full = dict(config or {})
        cfg = dict(full.get("source", {}) or {})
        cam_cfg = dict(full.get("camera", {}) or {})
        storage = dict(full.get("storage", {}) or {})
        self._raw_dir = str(storage.get("capture_raw_dir", "./logs/captures_raw"))
        self._result_dir = str(
            storage.get("capture_result_dir", "./logs/captures_result"))

        # 类型
        self.rb_folder = QRadioButton("文件夹")
        self.rb_single = QRadioButton("单图")
        self.rb_camera = QRadioButton("摄像头")
        stype = str(cfg.get("type", "folder") or "folder").lower()
        if stype == "camera":
            self.rb_camera.setChecked(True)
        elif stype == "single":
            self.rb_single.setChecked(True)
        else:
            self.rb_folder.setChecked(True)

        # 路径
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择文件夹或图片…")
        self.path_edit.setText(str(cfg.get("folder_path", "") or ""))
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)

        # 文件夹参数
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(50, 5000)
        self.interval_spin.setValue(int(cfg.get("poll_interval_ms", 300) or 300))
        self.interval_spin.setSuffix(" ms")
        # 循环播放：默认**不勾选**（`source.loop` 默认 false）。
        self.loop_check = QCheckBox("循环播放")
        self.loop_check.setChecked(bool(cfg.get("loop", False)))

        # 摄像头参数
        self.cam_combo = QComboBox()
        self.cam_combo.addItems(["0", "1", "2", "3"])
        cam_index = str(cfg.get("camera_index", 0))
        if self.cam_combo.findText(cam_index) >= 0:
            self.cam_combo.setCurrentText(cam_index)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(int(cfg.get("fps", 15) or 15))
        self.btn_test = QPushButton("测试摄像头")
        self.btn_test.clicked.connect(self.test_requested.emit)

        # 保存张数（会写回 config.yaml）
        self.spin_max_saved = QSpinBox()
        self.spin_max_saved.setRange(1, 999)
        self.spin_max_saved.setValue(int(cam_cfg.get("max_saved_images", 10) or 10))
        # 框里只放数字：单位由左边「保存张数:」这个标签表达，不再加 " 张" 后缀
        self.spin_max_saved.setSuffix("")
        self.spin_max_saved.valueChanged.connect(self.max_saved_changed.emit)
        self.btn_raw_hist = QPushButton("原图历史")
        self.btn_raw_hist.clicked.connect(
            lambda: self.open_dir_requested.emit(self._raw_dir))
        self.btn_result_hist = QPushButton("识别历史")
        self.btn_result_hist.clicked.connect(
            lambda: self.open_dir_requested.emit(self._result_dir))

        self.lbl_cam_status = QLabel("未连接相机")
        self.lbl_cam_status.setStyleSheet("color:#888;")
        self.lbl_cam_status.setWordWrap(True)

        self._running = False
        self._engine_busy = False

        # 按钮
        self.btn_start = QPushButton("▶ 开始")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self.stop_requested.emit)

        # ---- 布局 ----
        # ★ 每个可选行都套一个 QWidget 容器：整行（含「间隔:」「摄像头:」「FPS:」
        #   这些**标签**）一起显示/隐藏。只藏输入控件会留下孤儿标签 —— 这就是
        #   文件夹模式下看到「摄像头：FPS：保存：」那几行的原因。
        #   隐藏的 QWidget 在布局里不占任何高度，所以那几行会彻底消失。
        type_row = QHBoxLayout()
        type_row.addWidget(self.rb_folder)
        type_row.addWidget(self.rb_single)
        type_row.addWidget(self.rb_camera)
        type_row.addStretch()

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.btn_browse)
        self._row_path = self._wrap_row(path_row)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("间隔:"))
        folder_row.addWidget(self.interval_spin)
        folder_row.addWidget(self.loop_check)
        folder_row.addStretch()
        self._row_folder = self._wrap_row(folder_row)

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("摄像头:"))
        cam_row.addWidget(self.cam_combo)
        cam_row.addWidget(QLabel("FPS:"))
        cam_row.addWidget(self.fps_spin)
        cam_row.addWidget(self.btn_test)
        cam_row.addStretch()
        self._row_cam = self._wrap_row(cam_row)

        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("保存张数:"))
        save_row.addWidget(self.spin_max_saved)
        save_row.addWidget(self.btn_raw_hist)
        save_row.addWidget(self.btn_result_hist)
        save_row.addStretch()
        self._row_save = self._wrap_row(save_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(type_row)
        v.addWidget(self._row_path)
        v.addWidget(self._row_folder)
        v.addWidget(self._row_cam)
        v.addWidget(self._row_save)
        v.addWidget(self.lbl_cam_status)
        v.addLayout(btn_row)

        for rb in (self.rb_folder, self.rb_single, self.rb_camera):
            rb.toggled.connect(self._update_mode_visibility)
        self._update_mode_visibility()

    @staticmethod
    def _wrap_row(layout) -> QWidget:
        """把一行 QHBoxLayout 包成一个可整体隐藏的 QWidget。"""
        box = QWidget()
        box.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return box

    # ---- 模式联动 ---------------------------------------------------------
    def _update_mode_visibility(self, *_):
        is_camera = self.rb_camera.isChecked()
        is_folder = self.rb_folder.isChecked()
        self._row_path.setVisible(not is_camera)   # 相机模式没有路径可填
        self._row_folder.setVisible(is_folder)     # 间隔/循环只属于文件夹模式
        self._row_cam.setVisible(is_camera)        # 相机号/FPS/测试
        self._row_save.setVisible(is_camera)       # 保存张数/两个历史目录
        self.lbl_cam_status.setVisible(is_camera)

    def set_camera_status(self, text: str):
        self.lbl_cam_status.setText(text)

    # ---- 事件 -------------------------------------------------------------
    def _browse(self):
        if self.rb_single.isChecked():
            path, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "",
                "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        else:
            path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self.path_edit.setText(path)

    def _start(self):
        if self.rb_folder.isChecked():
            t = "folder"
        elif self.rb_single.isChecked():
            t = "single"
        else:
            t = "camera"

        path = self.path_edit.text().strip()
        if t != "camera" and not path:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先选择路径")
            return

        cfg = {
            "type": t,
            "path": path,
            "camera_index": int(self.cam_combo.currentText()),
            "fps": self.fps_spin.value(),
            "interval_ms": self.interval_spin.value(),
            "loop": self.loop_check.isChecked(),
        }
        self.set_running(True)
        self.start_requested.emit(cfg)

    def set_running(self, running: bool):
        self._running = bool(running)
        # 运行中允许再点「测试摄像头」是不合理的：那会抢相机
        self.btn_test.setEnabled(not running)
        self.btn_start.setEnabled(not running and not self._engine_busy)
        self.btn_stop.setEnabled(running)

    def set_engine_busy(self, busy: bool):
        """模型正在加载时禁掉「开始」：加载线程持着引擎锁，这时开跑会把
        推理线程堵在加载器后面。"""
        self._engine_busy = bool(busy)
        self.btn_start.setEnabled(not self._running and not self._engine_busy)

    def set_running_false(self):
        self.set_running(False)

    @property
    def max_saved(self) -> int:
        return self.spin_max_saved.value()
