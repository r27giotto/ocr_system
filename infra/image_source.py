import os
import threading

import cv2
from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class BaseSource(QObject):
    """所有图像源的基类。

    产出约定（★ 「每张图都要处理到」靠这三条保证）：

    - `frame_ready(frame, name)`：一张图读出来了，交给推理。
    - `read_failed(name)`：这张图**打不开**（坏文件 / 格式不支持）。它同样算
      一张图，必须上报，否则这张图就凭空消失了 —— 界面上没记录、CSV 少一行、
      串口少一个字节。
    - `frame_done()`：上一帧**已经处理完**（结果已分发、串口字节已写出），
      可以取下一帧了。输入源收到它才继续，所以任一时刻只有 1 帧在飞。
    """

    frame_ready = pyqtSignal(object, str)
    read_failed = pyqtSignal(str)
    finished = pyqtSignal()

    def start(self): ...
    def stop(self): ...

    def frame_done(self): ...


class FolderSource(BaseSource):
    """
    轮询文件夹，按文件名排序逐张产出。

    - 单图模式：传入单文件路径，只产出一帧后 finished。
    - 文件夹模式：默认**不循环**，放完一遍就 finished；loop=True 才从头再来。

    节奏：定时器是 **single-shot**，每次只发一张，等 `frame_done()` 回来
    才重新上弦。所以 `interval_ms` 是「上一帧处理完后再等多久」，
    不是固定帧率 —— 慢一点，但**一张都不会漏**。
    """

    def __init__(self, path: str, interval_ms: int = 300, loop: bool = False):
        super().__init__()
        self.path = path
        self.interval_ms = max(0, int(interval_ms))
        self.loop = loop
        self._files: list[str] = []
        self._idx = 0
        self._running = False
        self._inflight = False          # 已发出去、还没收到 frame_done
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    def _scan(self):
        if os.path.isfile(self.path):
            self._files = [self.path]
        else:
            self._files = [
                os.path.join(self.path, n)
                for n in sorted(os.listdir(self.path))
                if n.lower().endswith(IMG_EXTS)
            ]

    def start(self):
        self._scan()
        self._idx = 0
        self._inflight = False
        self._running = True
        if not self._files:
            self._running = False
            self.finished.emit()
            return
        self._timer.start(self.interval_ms)

    def _tick(self):
        if self._inflight or not self._running:
            return
        if self._idx >= len(self._files):
            if self.loop and len(self._files) > 1:
                self._idx = 0
            else:
                self._running = False
                self.finished.emit()
                return
        path = self._files[self._idx]
        self._idx += 1
        self._inflight = True           # 先置位，避免重入
        img = cv2.imread(path)
        if img is None:
            # 打不开也得上报，等 ack 后再继续
            self.read_failed.emit(os.path.basename(path))
            return
        self.frame_ready.emit(img, os.path.basename(path))

    def frame_done(self):
        self._inflight = False
        if self._running:
            self._timer.start(self.interval_ms)

    def stop(self):
        self._running = False
        self._inflight = False
        self._timer.stop()


class CameraSource(QThread, BaseSource):
    """USB 摄像头源，独立线程读帧，避免阻塞 UI。

    ★ 不再「按 fps 闷头读」：读一帧 → 发给推理 → **等这一帧处理完** → 再读下一帧。
    原来那样读，推理排不过来时缓冲区里的帧会被顶掉，等于漏检。
    """

    frame_ready = pyqtSignal(object, str)
    read_failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, index: int = 0, fps: int = 15):
        QThread.__init__(self)
        self.index = index
        self.interval = 1.0 / max(1, fps)
        self._running = False
        self._ack = threading.Event()   # 跨线程放行，Event 本身是线程安全的

    def start(self):
        self._running = True
        QThread.start(self)

    def run(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)   # ★ Windows 用 DSHOW
        if not cap.isOpened():
            self._running = False
            self.finished.emit()
            return
        n = 0
        while self._running:
            self._ack.clear()
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            self.frame_ready.emit(frame, f"cam_{n:06d}")
            # 等这帧处理完；每 0.1s 醒一次好让 stop() 能及时退出
            while self._running and not self._ack.wait(0.1):
                pass
            if not self._running:
                break
            self.msleep(int(self.interval * 1000))
        cap.release()
        self._running = False
        self.finished.emit()

    def frame_done(self):
        self._ack.set()

    def stop(self):
        self._running = False
        self._ack.set()        # 唤醒可能正卡在等待里的读帧线程
        self.wait(2000)
