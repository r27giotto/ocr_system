import queue
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
