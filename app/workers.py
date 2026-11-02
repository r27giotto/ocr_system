import queue
import threading
import time
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from core.models import RecognitionResult
from core.pipeline import OcrPipeline


class EngineLoadWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, engine, rec_name: str, ori_name: str):
        super().__init__()
        self.engine = engine
        self.rec_name = rec_name
        self.ori_name = ori_name

    def run(self):
        try:
            self.engine.get_rec(self.rec_name, self.progress.emit)
            self.engine.get_ori(self.ori_name, self.progress.emit)
            self.done.emit(True, "模型已加载")
        except Exception as e:
            # 完整堆栈必须打到控制台：界面标签放不下，
            # 「加载失败」若只有一行摘要会让人无从下手。
            traceback.print_exc()
            self.done.emit(False, str(e))


class InferenceWorker(QThread):
    """串行处理每一帧。**不丢帧**。

    原来这里用 `queue.Queue(maxsize=1)`，满了就丢最旧帧 —— 那等于
    「界面闪过、但既没识别、也没写 CSV、也没发串口」。现在改成：

    - 队列不设上限，投进来的帧**一定**会被处理；
    - 每处理完一帧发一次 `frame_processed`，由控制器转给当前输入源；
    - 输入源收到这个信号才去取下一帧（见 `BaseSource.frame_done`），
      所以队列里实际最多只有 1 帧，不会无限堆积。

    这样「一张图进来 ⟺ 一个结果出去」是可数的：控制器用
    `frames_in` / `results_out` 两个计数器对账。
    """

    result_ready = pyqtSignal(object)
    frame_processed = pyqtSignal(str)   # 参数=文件名；每帧处理完（含出错）都发

    def __init__(self, pipeline: OcrPipeline):
        super().__init__()
        self.pipeline = pipeline
        self._q: queue.Queue = queue.Queue()   # 不设 maxsize：宁可慢，不可丢
        self._running = True

    def submit(self, frame, name: str) -> None:
        """投递一帧。永不丢弃（背压靠输入源的 frame_done 保证）。"""
        self._q.put((frame, name))

    def pending(self) -> int:
        """队里还没处理的帧数（正常应为 0 或 1）"""
        return self._q.qsize()

    def run(self):
        while self._running:
            try:
                frame, name = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                res = self.pipeline.run_on_image(frame, name)
            except Exception as e:
                # 异常也必须产出一个结果，否则这一帧就凭空消失了：
                # 界面上没记录、CSV 少一行、串口少一个字节。
                print("inference error:", e)
                traceback.print_exc()
                res = RecognitionResult(
                    filename=name, status="error", error_msg=str(e))
            try:
                self.result_ready.emit(res)
            finally:
                # 即使 UI 槽函数抛异常，也要放行下一帧，否则整条产线卡死
                self.frame_processed.emit(name)

    def stop(self):
        self._running = False
        self.wait(2000)


class CameraWorker(QThread):
    """Basler 取图线程，一个类管两种模式。

    - `mode="preview"`（对应界面「测试摄像头」）：关掉硬件触发，自己连续取图，
      只发 `preview` 给界面显示，**不进推理、不落盘、不发串口**。
    - `mode="capture"`（对应「开始」）：等电眼硬件触发，每取到一张就发
      `frame_ready`，然后**等控制器回一次 `frame_done()` 才取下一下**。
      这样和文件夹模式是同一套背压：一张图进 ⇒ 一个结果出，不丢帧。

    相机在 `run()` 里才打开 —— 打开失败要能变成一条 `error` 信号，而不是把
    界面线程卡住。
    """

    preview = pyqtSignal(object)             # 预览帧（np.ndarray，BGR）
    frame_ready = pyqtSignal(object, str)    # 交给推理
    opened = pyqtSignal(str)                 # 打开成功，参数=设备名
    error = pyqtSignal(str)
    warn = pyqtSignal(str)                   # 非致命：某特性不支持等

    def __init__(self, camera_cfg: dict, mode: str = "capture",
                 store=None, preview_fps: int = 10):
        super().__init__()
        self.camera_cfg = dict(camera_cfg or {})
        self.mode = mode
        self.store = store
        self.preview_interval = 1.0 / max(1, int(preview_fps))
        self._running = True
        self._ack = threading.Event()
        self._camera = None
        self._seq = 0

    # ---- 与 FolderSource 对齐的接口，控制器不用区分来源 ----
    def frame_done(self) -> None:
        self._ack.set()

    def stop(self) -> None:
        self._running = False
        self._ack.set()          # 唤醒可能在等 ack 的循环
        if not self.wait(3000):
            self.wait(2000)
        cam, self._camera = self._camera, None
        if cam is not None:
            cam.close()

    # ---- 线程主体 ----
    def run(self):
        from infra.basler_camera import BaslerCamera, CameraError

        cam = BaslerCamera(self.camera_cfg)
        self._camera = cam
        try:
            cam.open(mode="free" if self.mode == "preview" else "trigger")
        except CameraError as exc:
            self.error.emit(str(exc))
            return
        except Exception as exc:                      # pragma: no cover
            traceback.print_exc()
            self.error.emit("打开相机时发生未预期错误：%s" % (exc,))
            return
        for w in cam.warnings:
            self.warn.emit(w)
        self.opened.emit(cam.device_name or "Basler 相机")

        try:
            if self.mode == "preview":
                self._loop_preview(cam)
            else:
                self._loop_capture(cam)
        except Exception as exc:                      # pragma: no cover
            traceback.print_exc()
            self.error.emit("取图过程中出错：%s" % (exc,))
        finally:
            cam.close()
            self._camera = None

    def _loop_preview(self, cam):
        while self._running:
            t0 = time.time()
            frame = cam.grab(timeout_ms=500)
            if frame is not None and self._running:
                self.preview.emit(frame)
            rest = self.preview_interval - (time.time() - t0)
            if rest > 0:
                time.sleep(rest)

    def _loop_capture(self, cam):
        while self._running:
            frame = cam.grab()          # 超时返回 None：没工件过来，属正常
            if frame is None:
                continue
            if not self._running:
                break
            self._seq += 1
            name = "%s/%06d" % (self.store.session_name if self.store else "-",
                                self._seq)
            self._ack.clear()
            self.frame_ready.emit(frame, name)
            # 等这一帧处理完再取下一下（不丢帧）。stop() 会把 _ack 置起来。
            self._ack.wait(30.0)
