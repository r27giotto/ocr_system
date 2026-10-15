import queue
from PyQt6.QtCore import QThread, pyqtSignal

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
            self.done.emit(False, str(e))


class InferenceWorker(QThread):
    result_ready = pyqtSignal(object)

    def __init__(self, pipeline: OcrPipeline):
        super().__init__()
        self.pipeline = pipeline
        self._q: queue.Queue = queue.Queue(maxsize=1)   # 只保留最新帧
        self._running = True

    def submit(self, frame, name: str) -> None:
        """非阻塞投递；队列满则丢弃最旧帧（保证实时性）"""
        try:
            self._q.put_nowait((frame, name))
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait((frame, name))
            except queue.Full:
                pass

    def run(self):
        while self._running:
            try:
                frame, name = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                res = self.pipeline.run_on_image(frame, name)
                self.result_ready.emit(res)
            except Exception as e:
                print("inference error:", e)

    def stop(self):
        self._running = False
        self.wait(2000)