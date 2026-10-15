import sys
import os
import yaml

# 环境变量（与原脚本一致）
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["MKL_NUM_THREADS"] = "8"

import cv2
cv2.setNumThreads(1)

from PyQt6.QtWidgets import QApplication

from app.controller import AppController
from ui.main_window import MainWindow


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()

    app = QApplication(sys.argv)
    controller = AppController(config)

    win = MainWindow(controller, config)
    win.show()

    app.aboutToQuit.connect(controller.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()