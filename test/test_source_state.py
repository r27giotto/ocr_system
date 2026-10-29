"""回归测试：输入源「开始 / 停止 / 再开始」的按钮状态。

用户反馈的 bug（m00002）：点「开始」跑检测，点「停止」确实停了，
但「开始」按钮仍然是灰的，再也没法开始第二次检测。

根因：手动停止这条路径上没有任何「回到空闲」的状态转移 ——
`AppController.stop_source()` 只把 `current_source` 置 None，不发信号；
`SourcePanel` 的按钮状态又只在「自然跑完」（`source_finished`）时复位。

跑法（离屏，不需要显示器、不加载模型）：
    .venv\\Scripts\\python.exe test\\test_source_state.py
"""

import os
import shutil
import sys
import tempfile
import types

# 必须有：无显示器环境下建 QApplication
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 这个测试只关心「输入源 → 控制器 → 按钮」这条状态链，
# 不碰推理：假 pipeline 顶掉真 pipeline，同时把 paddlex 这个重型
# 依赖整体挡在门外（core/engine.py 只在加载模型时才真正用到它）。
_pdx = types.ModuleType("paddlex")
_pdx.create_model = lambda *a, **k: None      # noqa: E731
sys.modules.setdefault("paddlex", _pdx)

import cv2                                                    # noqa: E402
import numpy as np                                            # noqa: E402
import yaml                                                   # noqa: E402
from PyQt6.QtCore import QEventLoop, QTimer                   # noqa: E402
from PyQt6.QtWidgets import QApplication                      # noqa: E402

from app.controller import AppController                      # noqa: E402
from core.models import RecognitionResult                     # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402


class FakePipeline:
    """不出结果以外的任何副作用：一帧进 → 一个 ok 结果出。"""

    def run_on_image(self, img, filename=""):
        return RecognitionResult(
            filename=filename, number="12", confidence=0.99,
            angle=0, status="ok", output_value=1, hit=True, elapsed_ms=0.0)


def pump(ms: int):
    """在嵌套事件循环里跑 ms 毫秒，让定时器和跨线程信号都落地。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_images(folder: str, count: int = 2):
    """FolderSource 用 cv2.imread 读图，所以必须是真文件。"""
    for i in range(count):
        img = np.full((40, 60, 3), 20 + i * 40, dtype=np.uint8)
        ok = cv2.imwrite(os.path.join(folder, f"img{i}.png"), img)
        assert ok, "测试图片写不出来"


def main() -> int:
    app = QApplication(sys.argv)                      # noqa: F841

    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 临时目录放工程根目录（沙箱只授予了根路径，test/ 这类既有子目录会被拒），
    # 且**必须用 os.makedirs 建**：tempfile.mkdtemp 会按 0o700 建目录，
    # 生成只给 owner 的 DACL，沙箱的受限令牌反而写不进去。
    tmp = os.path.join(ROOT, "_state_%d" % os.getpid())
    os.makedirs(tmp, exist_ok=True)
    # ★ 别写进 logs/results.csv：CsvLogger 用 "w" 打开，会把真实记录清空
    cfg["app"]["csv_output"] = os.path.join(tmp, "results.csv")
    make_images(tmp)

    ctrl = AppController(cfg)
    ctrl.infer_worker.pipeline = FakePipeline()
    # 本测试只验「输入源状态机」，不加载模型；但 m00804 起
    # 控制器要求模型就绪才允许开始，所以这里显式标记为已加载。
    ctrl.mark_models_loaded("PP-OCRv6_small_rec", "PP-LCNet_x1_0_textline_ori")
    win = MainWindow(ctrl, cfg)
    panel = win.source_panel

    panel.rb_folder.setChecked(True)
    panel.path_edit.setText(tmp)
    panel.interval_spin.setValue(30)
    panel.loop_check.setChecked(True)

    try:
        pump(200)                 # 启动时的 singleShot（刷新串口）先跑完

        # 1) 开始 → 运行中
        panel.btn_start.click()
        pump(300)
        assert not panel.btn_start.isEnabled(), "运行中「开始」应该变灰"
        assert panel.btn_stop.isEnabled(), "运行中「停止」应该可点"
        print("[1] 开始 → 运行中  OK", flush=True)

        # 2) 停止 → 必须回到空闲   ★ 原 bug 就死在这
        panel.btn_stop.click()
        pump(300)
        assert panel.btn_start.isEnabled(), \
            "点了「停止」之后「开始」必须恢复可点（原 bug：一直灰着）"
        assert not panel.btn_stop.isEnabled(), "停止后「停止」应该变灰"
        assert ctrl.current_source is None, "停止后控制器不应还挂着输入源"
        print("[2] 停止 → 回到空闲  OK", flush=True)

        # 3) 再开始 → 还能跑第二轮
        panel.btn_start.click()
        pump(300)
        assert not panel.btn_start.isEnabled(), "第二次「开始」应重新进入运行中"
        assert panel.btn_stop.isEnabled()
        panel.btn_stop.click()
        pump(300)
        assert panel.btn_start.isEnabled(), "第二轮停止后同样要能再开始"
        print("[3] 再开始 → 再停止  OK", flush=True)

        # 4) 自然跑完（loop 关掉、放完一遍）也要回到空闲
        panel.loop_check.setChecked(False)
        panel.btn_start.click()
        pump(1200)
        assert panel.btn_start.isEnabled(), "跑完一轮后应自动回到空闲"
        assert ctrl.current_source is None, "跑完后控制器不应还挂着输入源"
        print("[4] 自然跑完 → 回到空闲  OK", flush=True)

        # 5) 空文件夹：start() 会同步发 finished，按钮不能卡在运行中
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        panel.path_edit.setText(empty)
        panel.btn_start.click()
        pump(300)
        assert panel.btn_start.isEnabled(), "空文件夹应立即回到空闲，不能卡在运行中"
        print("[5] 空文件夹 → 回到空闲  OK", flush=True)

        # 6) 路径不存在：start() 会抛异常，也必须退回空闲并说明原因
        panel.path_edit.setText(os.path.join(tmp, "no_such_dir"))
        errs = []
        ctrl.source_error.connect(errs.append)
        panel.btn_start.click()
        pump(200)
        assert panel.btn_start.isEnabled(), "启动失败后「开始」必须可点，不能卡灰"
        assert errs, "启动失败应通过 source_error 报出原因"
        assert "启动输入源失败" in win.status_bar.currentMessage(), \
            "启动失败的原因应显示在状态栏"
        print("[6] 路径不存在 → 回到空闲  OK", flush=True)
    finally:
        # 断言失败也要收线程，否则 QThread 还在跑会把解释器退出卡死
        ctrl.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("OK: 开始/停止/再开始 的按钮状态全部正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
