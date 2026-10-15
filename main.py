import sys
import os
import yaml

# 环境变量（与原脚本一致）
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["MKL_NUM_THREADS"] = "8"

# ★ 模型缓存改到项目内的 models/，不再用 ~/.paddlex
# PaddleX 在 import 时就把 PADDLE_PDX_CACHE_HOME 读进常量（paddlex/utils/cache.py:29），
# 所以必须在任何 paddlex 相关 import 之前设置。
# 目录结构必须是 <CACHE_HOME>/official_models/<模型名>/，模型不存在时会自动下载到这里。
os.environ.setdefault(
    "PADDLE_PDX_CACHE_HOME",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
)

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