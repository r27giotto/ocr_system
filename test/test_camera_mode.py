# -*- coding: utf-8 -*-
"""摄像头模式全流程测试：电眼触发 → 取图 → 推理 → 输出（CSV / 落盘 PNG / 串口）。

这个脚本把**真实的** `AppController` 跑起来（真模型、真 CSV、真落盘），
只把两个硬件换成替身：

- **相机**：`FakeBaslerCamera` 严格模拟 Basler 的 `LatestImageOnly` ——
  相机里只有一个缓冲槽，软件没取走的旧帧会被下一次触发**覆盖**（真丢件）。
  所以「取图与推理没解耦」这种回归，本脚本能真的抓出来，而不是自说自话。
- **串口**：`FakeSerial` 只记录发出去的字节，不需要真的插 Arduino。

用法::

    python test/test_camera_mode.py                 # 6 帧，每 80ms 触发一次
    python test/test_camera_mode.py -n 12 -i 300    # 12 帧，每 300ms 触发一次
    python test/test_camera_mode.py --images <目录>  # 换一批样张
    python test/test_camera_mode.py --keep          # 保留落盘目录

默认触发间隔（80ms）**故意快于**单帧推理（约 230ms），好让积压真的堆起来，
用来验证「一堆触发里一个工件都不会丢」。

退出码：全部通过 0，有任何一项不通过 1。
"""

import argparse
import copy
import glob
import os
import shutil
import sys
import threading
import time

# ---- 环境必须在 import cv2 / paddle 之前设好 ----
os.environ.setdefault("OMP_NUM_THREADS", "8")
os.environ.setdefault("MKL_NUM_THREADS", "8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)
os.environ.setdefault("PADDLE_PDX_CACHE_HOME",
                      os.path.join(PROJECT_ROOT, "models"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import cv2                                    # noqa: E402
import yaml                                   # noqa: E402
from PyQt6.QtCore import QCoreApplication     # noqa: E402

DEFAULT_IMAGES = r"E:\Python Project\project_0\data\test3"


# =========================================================================
# 替身 1：相机
# =========================================================================
class FakeBaslerCamera:
    """模拟「电眼每触发一次 → 相机拍一张」。

    `LatestImageOnly` 的关键行为：相机内**只有一个槽位**。软件还没取走时，
    新触发会直接把旧帧扔掉 —— 这正是 A3 丢工件的机制，必须如实模拟，
    否则这个测试就测不出「取图与推理是否已解耦」。
    """

    # 由 main() 在构造前赋值
    samples = []
    frames = 6
    interval_ms = 80

    trigger_ts = []          # 每次触发的 perf_counter 时刻
    overwritten = 0          # 相机里被覆盖掉的帧数（真丢件）

    def __init__(self, *args, **kwargs):
        self._slot = None
        self._cv = threading.Condition()
        self._firing_done = False
        self._opened = False
        self.device_name = "FakeBasler（模拟电眼触发）"
        self.warnings = []
        self._thread = None
        FakeBaslerCamera.trigger_ts = []
        FakeBaslerCamera.overwritten = 0

    # ---- 生命周期 ----
    def open(self, mode="trigger", serial=None):
        if not self.samples:
            raise RuntimeError("没有样张可喂给假相机")
        self._opened = True
        self._thread = threading.Thread(target=self._fire, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._opened = False
        with self._cv:
            self._firing_done = True
            self._cv.notify_all()

    # ---- 触发线程：固定间隔打一次 ----
    def _fire(self):
        for i in range(self.frames):
            time.sleep(self.interval_ms / 1000.0)
            if not self._opened:
                return
            img = self.samples[i % len(self.samples)]
            with self._cv:
                if self._slot is not None:
                    FakeBaslerCamera.overwritten += 1
                self._slot = img
                FakeBaslerCamera.trigger_ts.append(time.perf_counter())
                self._cv.notify_all()
        with self._cv:
            self._firing_done = True
            self._cv.notify_all()

    # ---- 取图：没图就阻塞等电眼（和真相机一样）----
    def grab(self, timeout_ms=1000):
        deadline = time.perf_counter() + timeout_ms / 1000.0
        with self._cv:
            while self._slot is None:
                if self._firing_done:
                    # 触发已打完：像真相机一样「等不到就超时返回」，
                    # 但别空转把 CPU 吃满。
                    self._cv.wait(0.02)
                    return None
                remain = deadline - time.perf_counter()
                if remain <= 0:
                    return None
                self._cv.wait(min(remain, 0.05))
            img, self._slot = self._slot, None
            return img


# =========================================================================
# 替身 2：串口
# =========================================================================
class FakeSerial:
    """只记录发出去的字节，不碰真串口。"""

    def __init__(self):
        self.is_open = True
        self.sent = []           # ['1' / '0', ...]
        self.port = "FAKE"

    def open(self, port, baud):
        self.is_open = True
        self.port = "%s@%d" % (port, baud)
        return True, "已连接 %s" % self.port

    def send_value(self, value):
        self.sent.append("1" if int(value) == 1 else "0")
        return True, ""

    def close(self):
        self.is_open = False


# =========================================================================
# 主流程
# =========================================================================
def load_config():
    with open(os.path.join(PROJECT_ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def pump(app, seconds):
    """跑一会儿 Qt 事件循环，让跨线程投递的信号真正落地。"""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


def main():
    ap = argparse.ArgumentParser(
        description="摄像头模式全流程测试（无需真实相机）")
    ap.add_argument("-n", "--frames", type=int, default=6, help="触发几次")
    ap.add_argument("-i", "--interval-ms", type=int, default=80,
                    help="电眼触发间隔（毫秒）")
    ap.add_argument("--images", default=DEFAULT_IMAGES, help="样张目录")
    ap.add_argument("--keep", action="store_true", help="保留落盘目录")
    ap.add_argument("--backlog", type=int, default=60,
                    help="允许积压的帧数上限（默认 60；设 1 是「反例对照」，"
                         "会看到相机内覆帧数 > 0、不丢帧检查故意失败）")
    ap.add_argument("--aggregate", action="store_true",
                    help="打印每个候选数字的聚合分（调试用，输出会很长）")
    args = ap.parse_args()

    if not os.path.isdir(args.images):
        print("样张目录不存在：%s" % args.images)
        return 2
    files = sorted(
        p for p in glob.glob(os.path.join(args.images, "*"))
        if os.path.splitext(p)[1].lower() in
        (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"))
    if not files:
        print("样张目录里没有图片：%s" % args.images)
        return 2
    samples = [cv2.imread(p, cv2.IMREAD_COLOR) for p in files]
    samples = [s for s in samples if s is not None]
    print("样张 %d 张（%s）" % (len(samples), args.images))

    # ---- 配置：落盘改到 logs/_camera_test，绝不碰真实历史 ----
    cfg = copy.deepcopy(load_config())
    root = os.path.join(PROJECT_ROOT, "logs", "_camera_test")
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    cfg.setdefault("storage", {})
    cfg["storage"]["capture_raw_dir"] = os.path.join(root, "captures_raw")
    cfg["storage"]["capture_result_dir"] = os.path.join(root, "captures_result")
    cfg.setdefault("camera", {})
    cfg["camera"]["max_saved_images"] = 9999      # 测试期间别滚动删
    cfg["camera"]["max_backlog"] = max(1, args.backlog)
    cfg.setdefault("recognizer", {})
    # 逐候选的聚合分打印会把速度表冲掉，默认关掉
    cfg["recognizer"]["debug_aggregate"] = bool(args.aggregate)
    cfg.setdefault("app", {})
    cfg["app"]["save_csv"] = True
    cfg["app"]["csv_output"] = os.path.join(root, "results_all.csv")

    FakeBaslerCamera.samples = samples
    FakeBaslerCamera.frames = args.frames
    FakeBaslerCamera.interval_ms = args.interval_ms

    # `CameraWorker.run()` 里才 `from infra.basler_camera import BaslerCamera`，
    # 所以在这里替换模块属性是有效的。
    import infra.basler_camera as basler_mod
    basler_mod.BaslerCamera = FakeBaslerCamera

    app = QCoreApplication(sys.argv[:1])

    from app.controller import AppController
    ctrl = AppController(cfg)
    ctrl.serial = FakeSerial()

    # ---- 1. 加载模型（走真实的加载流程）----
    rec = cfg["models"]["default_rec"]
    ori = cfg["models"]["default_ori"]
    print("加载模型：%s / %s …" % (rec, ori))
    t_load = time.perf_counter()
    ctrl.load_models(rec, ori)
    load_deadline = time.perf_counter() + 120
    while not ctrl.models_ready and time.perf_counter() < load_deadline:
        app.processEvents()
        time.sleep(0.01)
    if not ctrl.models_ready:
        print("模型加载失败（超时）")
        return 1
    print("模型就绪，用时 %.2fs" % (time.perf_counter() - t_load))

    # ---- 2. 挂上收集器 ----
    arrivals = []                      # [(到达时刻, RecognitionResult)]
    errors = []
    infer_ms = []

    ctrl.result_ready.connect(lambda r: arrivals.append((time.perf_counter(), r)))
    ctrl.source_error.connect(errors.append)

    orig_run = ctrl.pipeline.run_on_image

    def timed_run(frame, name):
        t0 = time.perf_counter()
        try:
            return orig_run(frame, name)
        finally:
            infer_ms.append((time.perf_counter() - t0) * 1000.0)

    ctrl.pipeline.run_on_image = timed_run

    # ---- 3. 开跑 ----
    ctrl.camera_tested = True          # 跳过「测试摄像头」的 UI 步骤
    print("开始取图：%d 次触发，间隔 %dms（单帧推理约 230ms，故意让积压堆起来）"
          % (args.frames, args.interval_ms))
    t_start = time.perf_counter()
    ctrl.start_source({"type": "camera"})

    peak = 0
    t_limit = time.perf_counter() + 30 + args.frames * 3.0
    while (len(arrivals) < args.frames and not errors
           and time.perf_counter() < t_limit):
        app.processEvents()
        peak = max(peak, ctrl.frames_in - ctrl.results_out)
        time.sleep(0.002)
    t_wall = time.perf_counter() - t_start

    ctrl.stop_source()
    pump(app, 0.3)

    # ---- 4. 逐帧打印 ----
    trig = FakeBaslerCamera.trigger_ts
    print()
    print("=" * 84)
    print("%-4s %-6s %-5s %-8s %-7s %-7s %9s %13s" % (
        "序号", "数字", "判定", "置信度", "角度", "状态", "推理ms", "触发→结果ms"))
    print("-" * 84)
    lat = []
    for i, (t_arr, res) in enumerate(arrivals):
        ms = (t_arr - trig[i]) * 1000.0 if i < len(trig) else float("nan")
        lat.append(ms)
        print("%-4d %-6s %-5s %-8.4f %-7s %-7s %9.1f %13.1f" % (
            i + 1,
            res.number or "--",
            res.output_text,
            res.confidence,
            "%d°" % res.angle if res.angle is not None else "--",
            res.status,
            infer_ms[i] if i < len(infer_ms) else float("nan"),
            ms))
    print("-" * 84)

    if lat:
        print("推理耗时   平均 %.1f ms   最小 %.1f   最大 %.1f" % (
            sum(infer_ms) / len(infer_ms), min(infer_ms), max(infer_ms)))
        print("触发→结果  平均 %.1f ms   最小 %.1f   最大 %.1f" % (
            sum(lat) / len(lat), min(lat), max(lat)))
        print("端到端吞吐 %.2f 帧/秒（受单帧推理限制，与触发快慢无关）" % (
            1000.0 / (sum(infer_ms) / len(infer_ms))))
    print("峰值积压 %d 帧   总耗时 %.2fs" % (peak, t_wall))
    if peak > 2:
        print()
        print("说明：上面的「触发→结果」越往后越大，是因为触发(%dms)快于单帧推理，"
              % args.interval_ms)
        print("      帧在队列里排队等着；工件一个没丢（见下面的覆盖数=0），"
              "只是延迟在累加。")
        print("      产线上要让延迟恒定，电眼间隔必须 >= 单帧推理耗时。")

    # ---- 5. 校验 ----
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print("%s %s%s" % ("OK  " if cond else "FAIL", name,
                           ("  " + detail) if detail else ""))
        if not cond:
            ok = False

    print()
    print("-" * 84)
    check("没有 source_error", not errors, "; ".join(str(e) for e in errors))
    check("触发 %d 次全部取到" % args.frames, ctrl.frames_in == args.frames,
          "frames_in=%d" % ctrl.frames_in)
    check("每帧都出了结果" , len(arrivals) == args.frames,
          "results=%d" % len(arrivals))
    check("相机内没有被覆盖（没漏取）", FakeBaslerCamera.overwritten == 0,
          "overwritten=%d" % FakeBaslerCamera.overwritten)
    check("每帧都发了串口字节", len(ctrl.serial.sent) == args.frames,
          "bytes=%d [%s]" % (len(ctrl.serial.sent), "".join(ctrl.serial.sent)))
    check("峰值积压没超过 max_backlog",
          peak <= cfg["camera"]["max_backlog"], "peak=%d" % peak)

    raw_files = glob.glob(os.path.join(
        cfg["storage"]["capture_raw_dir"], "*", "*.png"))
    res_files = glob.glob(os.path.join(
        cfg["storage"]["capture_result_dir"], "*", "*.png"))
    check("原图落盘 %d 张" % args.frames, len(raw_files) == args.frames,
          "got=%d" % len(raw_files))
    check("结果图落盘 %d 张" % args.frames, len(res_files) == args.frames,
          "got=%d" % len(res_files))

    session_csv = glob.glob(os.path.join(
        cfg["storage"]["capture_result_dir"], "*", "results.csv"))
    if session_csv:
        with open(session_csv[0], encoding="utf-8-sig") as f:
            rows = f.readlines()
        check("会话 CSV 有 %d 行数据" % args.frames,
              len(rows) == args.frames + 1, "lines=%d" % len(rows))
    else:
        check("会话 CSV 已生成", False, "没找到 results.csv")

    if os.path.isfile(cfg["app"]["csv_output"]):
        with open(cfg["app"]["csv_output"], encoding="utf-8-sig") as f:
            rows = f.readlines()
        check("全局 CSV 追加了 %d 行" % args.frames,
              len(rows) == args.frames + 1, "lines=%d" % len(rows))
    else:
        check("全局 CSV 已生成", False)

    print()
    print("落盘目录：%s" % root)
    if ok and not args.keep:
        shutil.rmtree(root, ignore_errors=True)
        print("（已清理；想看文件加 --keep）")
    else:
        print("（已保留，可自行查看）")

    ctrl.shutdown()
    app.processEvents()
    print()
    print("=" * 84)
    print("结果：%s" % ("全部通过" if ok else "有失败项，见上面的 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
