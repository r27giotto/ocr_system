import os
import cv2
from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class BaseSource(QObject):
    """所有图像源的基类，输出 (frame, name) 信号"""
    frame_ready = pyqtSignal(object, str)
    finished = pyqtSignal()

    def start(self): ...
    def stop(self): ...


class FolderSource(BaseSource):
    """
    轮询文件夹，按文件名排序逐张产出。
    - 单图模式：传入单文件路径，只产出一帧后 finished。
    - 文件夹模式：循环产出，可设 loop。
    """
    def __init__(self, path: str, interval_ms: int = 300, loop: bool = True):
        super().__init__()
        self.path = path
        self.interval_ms = interval_ms
        self.loop = loop
        self._files: list[str] = []
        self._idx = 0
        self._timer = QTimer()
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
        if not self._files:
            self.finished.emit()
            return
        self._timer.start(self.interval_ms)

    def _tick(self):
        if self._idx >= len(self._files):
            if self.loop and len(self._files) > 1:
                self._idx = 0
            else:
                self._timer.stop()
                self.finished.emit()
                return
        path = self._files[self._idx]
        self._idx += 1
        img = cv2.imread(path)
        if img is not None:
            self.frame_ready.emit(img, os.path.basename(path))

    def stop(self):
        self._timer.stop()


class CameraSource(QThread, BaseSource):
    """USB 摄像头源，独立线程读帧，避免阻塞 UI。"""
    frame_ready = pyqtSignal(object, str)
    finished = pyqtSignal()

    def __init__(self, index: int = 0, fps: int = 15):
        QThread.__init__(self)
        self.index = index
        self.interval = 1.0 / max(1, fps)
        self._running = False

    def start(self):
        self._running = True
        QThread.start(self)

    def run(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)   # ★ Windows 用 DSHOW
        if not cap.isOpened():
            self.finished.emit()
            return
        n = 0
        while self._running:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            self.frame_ready.emit(frame, f"cam_{n:06d}")
            self.msleep(int(self.interval * 1000))
        cap.release()
        self.finished.emit()

    def stop(self):
        self._running = False
        self.wait(2000)