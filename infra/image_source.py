import os

import cv2
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

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
