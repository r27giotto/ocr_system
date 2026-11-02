# -*- coding: utf-8 -*-
"""真实 Basler 相机的全流程测试：**网线连着的真相机** → 取图 → 推理 → 输出。

没有替身相机。脚本会先枚举设备，找不到相机就打印排查清单并退出（退出码 2）。
找到相机后用真实的 `BaslerCamera` 打开，跑真实的 `AppController`
（真模型、真 CSV、真落盘），只在「串口」上默认用替身（不接 Arduino 也能跑）。

两种触发方式：

- `--trigger software`（默认）：把相机的 `TriggerSource` 设成 `Software`，
  由脚本自己按 `--interval-ms` 发触发。**不用接电眼**，只要相机通电能出图。
- `--trigger hardware`：`TriggerSource=Line1`，等电眼真的给信号。
  这时脚本只负责等和统计，你自己触发（或让产线触发）。

用法::

    python test/test_camera_mode.py                    # 软件触发，5 帧，间隔 300ms
    python test/test_camera_mode.py -n 10 -i 250        # 10 帧，250ms 一发
    python test/test_camera_mode.py --trigger hardware  # 等电眼，建议配 --timeout 300
    python test/test_camera_mode.py --serial COM3       # 用真串口发字节
    python test/test_camera_mode.py --keep              # 保留落片目录

每帧打印：抓图 / 排队 / 推理 / 收尾 / 合计 五段耗时。
落盘目录固定为 `logs/_camera_test/`（已在 `.gitignore` 里），不碰真实历史。

退出码：全部通过 0，有失败项 1，找不到相机 2。
"""

import argparse
import copy
import glob
import os
import shutil
import sys
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

import yaml                                   # noqa: E402
from PyQt6.QtCore import QCoreApplication     # noqa: E402


# =========================================================================
# 串口替身（只需要记录字节；想用真串口加 --serial COM3）
# =========================================================================
class RecordSerial:
    """把 `send_value` 的字节记下来。`real=None` 时完全不碰硬件。"""

    def __init__(self, real=None):
        self._real = real
        self.is_open = True
        self.sent = []

    def open(self, port, baud):
        if self._real is not None:
            ok, msg = self._real.open(port, baud)
            self.is_open = ok
            return ok, msg
        self.is_open = True
        return True, "（替身）已连接"

    def send_value(self, value):
        self.sent.append("1" if int(value) == 1 else "0")
        if self._real is not None:
            return self._real.send_value(value)
        return True, ""

    def close(self):
        self.is_open = False
        if self._real is not None:
            self._real.close()


# =========================================================================
# 主线
# =========================================================================
def load_config():
    with open(os.path.join(PROJECT_ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_no_camera_help(pylon_version, err=None):
    print()
    print("=" * 78)
    print("没有找到 Basler 相机，无法进行真机测试。")
    print("  pypylon 版本 : %s" % (pylon_version or "（读不到）"))
    print("  枚举到的设备 : 0 台")
    if err:
        print("  枚举报错     : %s" % err)
    print()
    print("按顺序排查：")
    print("  1) 网线：相机 ↔ 电脑网卡（直连或经交换机都行，但别接到普通办公网）")
    print("  2) 供电：相机指示灯是否亮（acA1300-60gm 支持 PoE，也可 12V 供电）")
    print("  3) 网段：网卡 IP 要和相机同网段（新手常踩：网卡是 192.168.1.x，")
    print("           相机是 169.254.x.x，两边永远看不见）")
    print("  4) 巨帧：网卡 Jumbo Frame 设 9014，相机侧 Packet Size 相应调大")
    print("  5) 占用：Pylon Viewer 或别的程序是否已打开这台相机（独占）")
    print("  6) 验证：先开 Pylon Viewer，能出图说明链路是好的，再来跑本脚本")
    print()
    print("想先用界面点一遍：双击 OCR系统.lnk → 选「摄像头」→ 点「测试摄像头」")
    print("=" * 78)
    return 2


def main():
    ap = argparse.ArgumentParser(
        description="真实 Basler 相机全流程测试（需要网线连接相机）")
    ap.add_argument("-n", "--frames", type=int, default=5, help="触发几次（默认 5）")
    ap.add_argument("-i", "--interval-ms", type=int, default=300,
                    help="软件触发的间隔毫秒（默认 300）")
    ap.add_argument("--trigger", choices=["software", "hardware"],
                    default="software", help="触发方式（默认 software）")
    ap.add_argument("--exposure-us", type=float, default=None,
                    help="曝光微秒（默认用 config.yaml 的 camera.exposure_us）")
    ap.add_argument("--serial", default=None,
                    help="用这个真串口发字节（如 COM3）；不给就用替身")
    ap.add_argument("--timeout", type=float, default=None,
                    help="等结果的超时秒数（默认 30 + 帧数×10）")
    ap.add_argument("--keep", action="store_true", help="保留落盘目录")
    args = ap.parse_args()

    # ---- 0. 先确认真的有相机 ----
    import infra.basler_camera as bc
    try:
        pylon_mod = bc.pylon_module()
        ver = getattr(pylon_mod, "__version__", None)
        if not ver:
            try:
                ver = pylon_mod.PylonVersion().Version
            except Exception:
                ver = "?"
    except bc.CameraError as exc:
        print(str(exc))
        return 2
    try:
        devices = bc.enumerate_devices()
    except bc.CameraError as exc:
        return print_no_camera_help(ver, exc)
    if not devices:
        return print_no_camera_help(ver)
    print("pypylon %s，找到 %d 台相机：" % (ver, len(devices)))
    for d in devices:
        print("  - %s" % d)

    # ---- 1. 配置 ----
    cfg = copy.deepcopy(load_config())
    root = os.path.join(PROJECT_ROOT, "logs", "_camera_test")
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    cfg.setdefault("storage", {})
    cfg["storage"]["capture_raw_dir"] = os.path.join(root, "captures_raw")
    cfg["storage"]["capture_result_dir"] = os.path.join(root, "captures_result")
    cfg.setdefault("camera", {})
    cfg["camera"]["max_saved_images"] = 9999        # 测试期间别滚动删
    cfg["camera"]["max_backlog"] = 60
    cfg["camera"]["trigger_source"] = ("Software" if args.trigger == "software"
                                       else cfg["camera"].get("trigger_line", "Line1"))
    if args.exposure_us:
        cfg["camera"]["exposure_us"] = args.exposure_us
    cfg.setdefault("recognizer", {})
    cfg["recognizer"]["debug_aggregate"] = False     # 别把速度表冲掉
    cfg.setdefault("app", {})
    cfg["app"]["save_csv"] = True
    cfg["app"]["csv_output"] = os.path.join(root, "results_all.csv")

    # ---- 2. 建控制器 ----
    app = QCoreApplication(sys.argv[:1])
    from app.controller import AppController

    ctrl = AppController(cfg)
    if args.serial:
        from infra.serial_service import SerialService
        ctrl.serial = RecordSerial(SerialService())
        ctrl.open_serial(args.serial, cfg.get("serial", {}).get("baudrate", 115200))
        print("串口：真串口 %s" % args.serial)
    else:
        ctrl.serial = RecordSerial()
        print("串口：替身（加 --serial COM3 可用真串口）")

    rec = cfg["models"]["default_rec"]
    ori = cfg["models"]["default_ori"]
    print("加载模型：%s / %s …" % (rec, ori))
    t0 = time.perf_counter()
    ctrl.load_models(rec, ori)
    deadline = time.perf_counter() + 120
    while not ctrl.models_ready and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if not ctrl.models_ready:
        print("模型加载失败（超时）")
        return 1
    print("模型就绪，用时 %.2fs" % (time.perf_counter() - t0))

    # ---- 3. 挂计时钩子 ----
    submits = []          # 取到帧、交给推理线程的时刻
    infers = []           # (开始, 结束)
    arrivals = []         # (结果到达时刻, RecognitionResult)
    errors = []

    orig_submit = ctrl.infer_worker.submit

    def submit_spy(*a, **kw):
        submits.append(time.perf_counter())
        return orig_submit(*a, **kw)

    ctrl.infer_worker.submit = submit_spy

    orig_run = ctrl.pipeline.run_on_image

    def run_spy(frame, name):
        t = time.perf_counter()
        try:
            return orig_run(frame, name)
        finally:
            infers.append((t, time.perf_counter()))

    ctrl.pipeline.run_on_image = run_spy

    ctrl.result_ready.connect(lambda r: arrivals.append((time.perf_counter(), r)))
    ctrl.source_error.connect(errors.append)

    # ---- 4. 开跑 ----
    ctrl.camera_tested = True            # 跳过界面上的「测试摄像头」步骤
    print()
    print("开始：%d 帧，触发方式 = %s%s" % (
        args.frames, args.trigger,
        ("，间隔 %dms" % args.interval_ms) if args.trigger == "software" else
        "（请触发电眼）"))
    t_start = time.perf_counter()
    ctrl.start_source({"type": "camera"})

    # 等取图线程把相机打开
    src = ctrl.current_source
    wait_end = time.perf_counter() + 15
    while time.perf_counter() < wait_end:
        app.processEvents()
        if src is not None and getattr(src, "_camera", None) is not None:
            break
        time.sleep(0.02)
    cam = getattr(src, "_camera", None) if src is not None else None
    if cam is None:
        print("相机没能打开：%s" % ("; ".join(errors) or "线程未就绪"))
        ctrl.stop_source()
        return 1
    print("相机已打开：%s" % (cam.device_name or "?"))
    for w in cam.warnings:
        print("  [警告] %s" % w)
    if args.trigger == "software":
        print("相机内缓冲策略 = LatestImageOnly（软件取不走时相机里会被覆盖）")

    # ---- 5. 触发 ----
    trig_ts = []
    if args.trigger == "software":
        for i in range(args.frames):
            if i:
                time.sleep(args.interval_ms / 1000.0)
            app.processEvents()
            try:
                cam.software_trigger()
            except bc.CameraError as exc:
                print("软件触发失败：%s" % exc)
                break
            trig_ts.append(time.perf_counter())
        print("已发 %d 次软件触发，等结果…" % len(trig_ts))
    else:
        print("等电眼触发（最多 %.0f 秒）…" % (args.timeout or (30 + args.frames * 10)))

    # ---- 6. 等结果 ----
    limit = time.perf_counter() + (args.timeout or (30 + args.frames * 10))
    last_n = -1
    while (len(arrivals) < args.frames and not errors
           and time.perf_counter() < limit):
        app.processEvents()
        if len(arrivals) != last_n:
            last_n = len(arrivals)
            print("  …已收到 %d/%d" % (len(arrivals), args.frames))
        time.sleep(0.005)
    t_wall = time.perf_counter() - t_start

    ctrl.stop_source()
    for _ in range(60):
        app.processEvents()
        time.sleep(0.005)

    # ---- 7. 逐帧速度表 ----
    print()
    print("=" * 100)
    print("%-4s %-6s %-5s %-8s %-6s %-12s %7s %7s %8s %7s %7s" % (
        "序号", "数字", "判定", "置信度", "角度", "状态",
        "抓图", "排队", "推理", "收尾", "合计"))
    print("-" * 100)
    rows = []
    for i, (t_arr, res) in enumerate(arrivals):
        t_sub = submits[i] if i < len(submits) else None
        inf = infers[i] if i < len(infers) else None
        t_trig = trig_ts[i] if i < len(trig_ts) else None
        grab_ms = ((t_sub - t_trig) * 1000) if (t_sub and t_trig) else None
        queue_ms = ((inf[0] - t_sub) * 1000) if (inf and t_sub) else None
        infer_ms = ((inf[1] - inf[0]) * 1000) if inf else None
        tail_ms = ((t_arr - inf[1]) * 1000) if inf else None
        total_ms = ((t_arr - (t_trig or t_sub)) * 1000) if (t_trig or t_sub) else None
        rows.append((grab_ms, queue_ms, infer_ms, tail_ms, total_ms))
        print("%-4d %-6s %-5s %-8.4f %-6s %-12s %7s %7s %8s %7s %7s" % (
            i + 1,
            res.number or "--",
            res.output_text,
            res.confidence,
            ("%d°" % res.angle) if res.angle is not None else "--",
            res.status,
            "%.0f" % grab_ms if grab_ms is not None else "—",
            "%.0f" % queue_ms if queue_ms is not None else "—",
            "%.0f" % infer_ms if infer_ms is not None else "—",
            "%.0f" % tail_ms if tail_ms is not None else "—",
            "%.0f" % total_ms if total_ms is not None else "—"))
    print("-" * 100)

    def avg(idx):
        vals = [r[idx] for r in rows if r[idx] is not None]
        return sum(vals) / len(vals) if vals else float("nan")

    if rows:
        print("平均：抓图 %.0fms │ 排队 %.0fms │ 推理 %.0fms │ 收尾 %.0fms │ 合计 %.0fms"
              % (avg(0), avg(1), avg(2), avg(3), avg(4)))
        if avg(2) == avg(2) and avg(2) > 0:
            print("按推理算吞吐上限：%.2f 帧/秒（%.0fms/帧）"
                  % (1000.0 / avg(2), avg(2)))
        print("本次总耗时 %.2fs" % t_wall)

    # ---- 8. 校验 ----
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print("%s %s%s" % ("OK  " if cond else "FAIL", name,
                           ("  " + detail) if detail else ""))
        if not cond:
            ok = False

    print()
    print("-" * 100)
    check("没有 source_error", not errors, "; ".join(str(e) for e in errors))
    check("每帧都取到并处理", ctrl.frames_in == len(arrivals) == len(submits),
          "frames_in=%d results=%d submits=%d"
          % (ctrl.frames_in, len(arrivals), len(submits)))
    if args.trigger == "software":
        check("软件触发 %d 次全出图" % args.frames,
              ctrl.frames_in >= args.frames, "frames_in=%d" % ctrl.frames_in)
    check("每帧都发了串口字节", len(ctrl.serial.sent) == len(arrivals),
          "bytes=%d [%s]" % (len(ctrl.serial.sent), "".join(ctrl.serial.sent)))

    n = len(arrivals)
    raw_files = glob.glob(os.path.join(
        cfg["storage"]["capture_raw_dir"], "*", "*.png"))
    res_files = glob.glob(os.path.join(
        cfg["storage"]["capture_result_dir"], "*", "*.png"))
    check("原图落盘 %d 张" % n, len(raw_files) == n, "got=%d" % len(raw_files))
    check("结果图落盘 %d 张" % n, len(res_files) == n, "got=%d" % len(res_files))

    session_csv = glob.glob(os.path.join(
        cfg["storage"]["capture_result_dir"], "*", "results.csv"))
    if session_csv:
        with open(session_csv[0], encoding="utf-8-sig") as f:
            lines = f.readlines()
        check("会话 CSV 有 %d 行数据" % n, len(lines) == n + 1,
              "lines=%d" % len(lines))
    else:
        check("会话 CSV 已生成", False, "没找到 results.csv")

    if os.path.isfile(cfg["app"]["csv_output"]):
        with open(cfg["app"]["csv_output"], encoding="utf-8-sig") as f:
            lines = f.readlines()
        check("全局 CSV 追加了 %d 行" % n, len(lines) == n + 1,
              "lines=%d" % len(lines))
    else:
        check("全局 CSV 已生成", False)

    if n and n < args.frames:
        print()
        print("提示：只收到 %d/%d 帧。软件触发模式下说明有触发没出图 ——"
              % (n, args.frames))
        print("      看上面的「抓图」耗时；若某帧一直是 —，可能是曝光/带宽跟不上。")

    print()
    print("落盘目录：%s" % root)
    if ok and not args.keep:
        shutil.rmtree(root, ignore_errors=True)
        print("（已清理；想看图片/CSV 加 --keep）")
    else:
        print("（已保留）")

    ctrl.shutdown()
    app.processEvents()
    print()
    print("=" * 100)
    print("结果：%s" % ("全部通过" if ok else "有失败项，见上面的 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
