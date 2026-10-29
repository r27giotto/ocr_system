"""回归测试：模型「没加载 / 正在加载 / 加载失败」时不许开跑（m00804，对应缺陷 D13）。

背景（J5 的备注只写了「加载中用户可能误点开始」，实际缺口更大）：
1. 加载线程持着 `EngineManager` 的锁几秒，而 `Recognizer.recognize()` 第一件事
   就是 `engine.get_rec()` 拿同一把锁 —— 加载中开跑会把**输入源线程**堵住。
2. 以前 `load_models()` 一开头就 `rec.set_models(新名字)`，加载失败后
   `rec_model_name` 已是新名字，之后**每一帧**都抛
   `No engine bindings registered for model '<名>'`。
3. `engine_status` 只带 `(ok, msg)`，切了下拉框没点加载，界面仍绿色「已加载」。

本测试**不加载真实模型**（paddlex 被桩掉），只验状态机与界面联动。
跑法：
    .venv\\Scripts\\python.exe test\\test_engine_ready.py
"""

import os
import shutil
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 重型依赖挡在门外：本测试只测状态机，不碰推理/加载
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

REC = "PP-OCRv6_small_rec"
ORI = "PP-LCNet_x1_0_textline_ori"


class FakePipeline:
    def run_on_image(self, img, filename=""):
        return RecognitionResult(
            filename=filename, number="12", confidence=0.99,
            angle=0, status="ok", output_value=1, hit=True, elapsed_ms=0.0)


def pump(ms: int):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_images(folder: str, count: int = 2):
    for i in range(count):
        img = np.full((40, 60, 3), 20 + i * 40, dtype=np.uint8)
        assert cv2.imwrite(os.path.join(folder, f"img{i}.png"), img)


def main() -> int:
    app = QApplication(sys.argv)                      # noqa: F841

    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    tmp = os.path.join(ROOT, "_ready_%d" % os.getpid())
    os.makedirs(tmp, exist_ok=True)
    cfg["app"]["csv_output"] = os.path.join(tmp, "results.csv")
    make_images(tmp)

    ctrl = AppController(cfg)
    ctrl.infer_worker.pipeline = FakePipeline()
    win = MainWindow(ctrl, cfg)
    src = win.source_panel
    mp = win.model_panel

    src.rb_folder.setChecked(True)
    src.path_edit.setText(tmp)
    src.interval_spin.setValue(30)
    src.loop_check.setChecked(True)

    errs = []
    ctrl.source_error.connect(errs.append)
    statuses = []
    ctrl.engine_status.connect(lambda ok, msg, name: statuses.append((ok, msg, name)))

    try:
        pump(200)

        # 1) 未加载 → 点开始必须被拒，且按钮不能卡灰
        assert not ctrl.models_ready
        src.btn_start.click()
        pump(150)
        assert ctrl.current_source is None, "模型未加载却开始了"
        assert errs and "模型未加载" in errs[-1], f"应提示未加载，实际 {errs}"
        assert src.btn_start.isEnabled(), "被拒后「开始」必须还能点"
        assert not src.btn_stop.isEnabled()
        print("[1] 未加载 → 拒绝开始  OK", flush=True)

        # 2) 加载中 → 开始按钮禁用（UI 层）；控制器层也要拦（防止别的入口绕过按钮）
        ctrl.engine_busy.emit(True)
        pump(50)
        assert not src.btn_start.isEnabled(), "加载中「开始」应禁用"
        assert "加载" in src.btn_start.toolTip(), "加载中应有 tooltip 说明"
        ctrl._loading = True
        errs.clear()
        # 直接调控制器：禁用按钮的 click() 在 Qt 里根本不会触发，绕不过按钮那层
        ctrl.start_source({"type": "folder", "path": tmp, "camera_index": 0,
                           "fps": 15, "interval_ms": 30, "loop": True})
        pump(150)
        assert ctrl.current_source is None, "加载中不该开跑"
        assert errs and "模型正在加载" in errs[-1], f"应提示正在加载，实际 {errs}"
        ctrl._loading = False
        ctrl.engine_busy.emit(False)
        pump(50)
        assert src.btn_start.isEnabled(), "加载结束后「开始」应恢复"
        print("[2] 加载中 → 禁止开始  OK", flush=True)

        # 3) 加载失败 → 仍不可开始，面板红字，且**模型名没被污染**
        ctrl._on_load_done(False, "create_model 失败: 模型文件不存在", REC, ORI)
        pump(50)
        assert not ctrl.models_ready, "失败后不应认为就绪"
        assert ctrl.rec.rec_model_name == "", \
            f"加载失败不该改 Recognizer 的模型名，实际 {ctrl.rec.rec_model_name!r}"
        assert "加载失败" in mp.status_label.text()
        errs.clear()
        src.btn_start.click()
        pump(150)
        assert ctrl.current_source is None and "模型未加载" in errs[-1]
        print("[3] 加载失败 → 拒绝开始且模型名未污染  OK", flush=True)

        # 4) 加载成功 → 开始按钮可用、面板显示具体模型名
        ctrl._on_load_done(True, "模型已加载", REC, ORI)
        pump(50)
        assert ctrl.models_ready
        assert ctrl.rec.rec_model_name == REC
        assert REC in mp.status_label.text(), f"标签应写出模型名：{mp.status_label.text()!r}"
        assert "已加载" in mp.status_label.text()
        assert src.btn_start.isEnabled()
        assert mp.rec_combo.isEnabled(), "加载结束后下拉框应恢复可改"
        print("[4] 加载成功 → 可以开始  OK", flush=True)

        # 5) 切下拉框但没点加载 → 面板必须提示「未加载」，不能仍显示绿色已加载
        other = ctrl.config["models"]["rec_options"][1]
        mp.rec_combo.setCurrentText(other)
        pump(50)
        text = mp.status_label.text()
        assert REC in text and "未加载" in text, f"应提示切换后未加载：{text!r}"
        assert "已加载：" not in text
        print("[5] 切换模型未加载 → 界面如实提示  OK", flush=True)

        # 6) 加载成功后可以真正跑起来
        mp.rec_combo.setCurrentText(REC)
        src.btn_start.click()
        pump(400)
        assert ctrl.current_source is not None, "模型就绪后应能开始"
        assert not src.btn_start.isEnabled()
        assert src.btn_stop.isEnabled()

        # 7) 运行中调 load_models → 必须被拒（否则推理线程会被加载锁堵住）
        before = ctrl._load_worker
        statuses.clear()
        ctrl.load_models(other, ORI)
        pump(100)
        assert ctrl._load_worker is before, "运行中不该真的起加载线程"
        assert not ctrl._loading
        assert statuses and statuses[-1][0] is False
        assert "运行" in statuses[-1][1], f"应说明运行中不许加载：{statuses[-1]}"
        assert ctrl.current_source is not None, "被拒的加载不该影响正在跑的检测"

        src.btn_stop.click()
        pump(300)
        assert src.btn_start.isEnabled(), "停止后应回到空闲"
        print("[6] 运行中拒绝加载  OK", flush=True)
    finally:
        ctrl.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("OK: 未加载/加载中/加载失败 三种状态都拦住了，模型名不再被污染")
    return 0


if __name__ == "__main__":
    sys.exit(main())
