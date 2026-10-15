from PyQt6.QtWidgets import (
    QGroupBox, QRadioButton, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QFileDialog, QHBoxLayout, QVBoxLayout, QLabel
)
from PyQt6.QtCore import pyqtSignal


class SourcePanel(QGroupBox):
    start_requested = pyqtSignal(dict)
    stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__("输入源")

        # 类型
        self.rb_folder = QRadioButton("文件夹")
        self.rb_single = QRadioButton("单图")
        self.rb_camera = QRadioButton("摄像头")
        self.rb_folder.setChecked(True)

        # 路径
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择文件夹或图片…")
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)

        # 摄像头参数
        self.cam_combo = QComboBox()
        self.cam_combo.addItems(["0", "1", "2", "3"])
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(15)

        # 文件夹参数
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(50, 5000)
        self.interval_spin.setValue(300)
        self.interval_spin.setSuffix(" ms")
        self.loop_check = QCheckBox("循环播放")
        self.loop_check.setChecked(True)

        # 按钮
        self.btn_start = QPushButton("▶ 开始")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self.stop_requested.emit)

        # 布局
        type_row = QHBoxLayout()
        type_row.addWidget(self.rb_folder)
        type_row.addWidget(self.rb_single)
        type_row.addWidget(self.rb_camera)
        type_row.addStretch()

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.btn_browse)

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("摄像头:"))
        cam_row.addWidget(self.cam_combo)
        cam_row.addWidget(QLabel("FPS:"))
        cam_row.addWidget(self.fps_spin)
        cam_row.addWidget(QLabel("间隔:"))
        cam_row.addWidget(self.interval_spin)
        cam_row.addWidget(self.loop_check)
        cam_row.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(type_row)
        v.addLayout(path_row)
        v.addLayout(cam_row)
        v.addLayout(btn_row)

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
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def set_running_false(self):
        self.set_running(False)