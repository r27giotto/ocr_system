"""程序入口：启动 OCR 识别系统的图形界面。

两种启动方式等价：
1. 双击项目根目录的「OCR系统」快捷方式（用 `pythonw.exe` 拉起，不弹黑框）
2. 在项目根目录执行 `.venv\\Scripts\\python.exe main.py`

无论从哪里启动，都先 `chdir` 到本文件所在目录 —— `config.yaml`、`./logs`、
`./models` 都是相对路径，工作目录不对就会读到别处的配置、把 CSV 写到莫名其妙的地方。
"""

import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用 pythonw.exe（无控制台）启动时 sys.stdout / sys.stderr 是 None，
# 而项目里有多处 print（debug_aggregate、paddlex 进度条…），
# print 到 None 会抛 AttributeError —— 先接到空设备上。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = sys.stdout

os.environ["OMP_NUM_THREADS"] = "8"
os.environ["MKL_NUM_THREADS"] = "8"

try:
    os.chdir(BASE_DIR)
except OSError:
    pass

# ★ 模型缓存指向项目内的 models/，不再读 ~/.paddlex。
# PaddleX 在 import 时就把 PADDLE_PDX_CACHE_HOME 读成常量（paddlex/utils/cache.py:29），
# 所以必须在任何 paddlex 相关 import 之前设置。
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.join(BASE_DIR, "models"))

import cv2                                                        # noqa: E402
cv2.setNumThreads(1)

import yaml                                                       # noqa: E402
from PyQt6.QtWidgets import QApplication                          # noqa: E402

from app.controller import AppController                          # noqa: E402
from ui.main_window import MainWindow                             # noqa: E402

CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
_faulthandler_file = None      # 持有引用，否则被 GC 后 faulthandler 就断了


def install_crash_log():
    """`pythonw.exe` 启动没有控制台：未捕获的异常要落到 logs\\crash.log。"""
    log_dir = os.path.join(BASE_DIR, "logs")

    def hook(exc_type, exc, tb):
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "crash.log"), "a",
                      encoding="utf-8") as f:
                f.write("=" * 70 + "\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = hook

    # 定位 DLL 级崩溃（Qt/OpenCV/paddle 的原生段错误不走 excepthook）
    global _faulthandler_file
    try:
        import faulthandler
        os.makedirs(log_dir, exist_ok=True)
        _faulthandler_file = open(os.path.join(log_dir, "crash.log"), "a",
                                  encoding="utf-8")
        faulthandler.enable(_faulthandler_file)
    except Exception:
        _faulthandler_file = None


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    install_crash_log()
    config = load_config()

    app = QApplication(sys.argv)
    controller = AppController(config)

    win = MainWindow(controller, config)
    win.show()

    app.aboutToQuit.connect(controller.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
