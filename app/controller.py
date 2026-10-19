from PyQt6.QtCore import QObject, pyqtSignal

from core.engine import EngineManager
from core.models import RecognitionResult
from core.preprocess import Preprocessor, PreprocessConfig
from core.recognizer import Recognizer, RecognizerConfig
from core.decision import DecisionMaker
from core.pipeline import OcrPipeline
from infra.serial_service import SerialService
from infra.csv_logger import CsvLogger
from infra.image_source import FolderSource, CameraSource

from app.workers import EngineLoadWorker, InferenceWorker


class AppController(QObject):
    # 向 UI 发信号
    frame_ready = pyqtSignal(object, str)
    result_ready = pyqtSignal(object)
    serial_sent = pyqtSignal(int, bool, str)
    engine_status = pyqtSignal(bool, str)   # 终态：模型加载完成/失败
    engine_progress = pyqtSignal(str)       # 过程：正在加载哪个模型
    source_finished = pyqtSignal()

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

        # ---- 核心层 ----
        self.engine = EngineManager()
        pre_cfg = PreprocessConfig(**{
            k: tuple(v) if isinstance(v, list) else v
            for k, v in config.get("preprocess", {}).items()
        })
        rec_cfg = RecognizerConfig(**{
            k: tuple(v) if isinstance(v, list) else v
            for k, v in config.get("recognizer", {}).items()
        })
        self.pre = Preprocessor(pre_cfg)
        self.rec = Recognizer(self.engine, self.pre, rec_cfg)
        self.decider = DecisionMaker(
            set(config["target"]["numbers"]),
            config["target"].get("valid_min", 1),
            config["target"].get("valid_max", 48),
        )
        self.pipeline = OcrPipeline(self.pre, self.rec, self.decider)

        # ---- 基础设施 ----
        self.serial = SerialService()
        self.csv = CsvLogger(config["app"]["csv_output"])

        # ---- 推理线程 ----
        self.infer_worker = InferenceWorker(self.pipeline)
        self.infer_worker.result_ready.connect(self._on_result)
        # 每处理完一帧就放行输入源，去取下一帧（见 InferenceWorker 的说明）
        self.infer_worker.frame_processed.connect(self._on_frame_processed)
        self.infer_worker.start()

        # ---- 状态 ----
        self.current_source = None
        # ★ 对账计数器：进来的帧数 vs 出去的结果数。
        #   两者相等 = 每张图都处理到了；不等就说明有帧卡在队列里。
        self.frames_in = 0
        self.results_out = 0

    # ---------- 模型 ----------
    def load_models(self, rec_name: str, ori_name: str):
        self.rec.set_models(rec_name, ori_name)
        self._load_worker = EngineLoadWorker(self.engine, rec_name, ori_name)
        # 进度和终态必须走两条信号：engine_status 带 ok 布尔，
        # 之前把进度也塞进它（ok=False），界面就把「正在加载 X」当成「加载失败」。
        self._load_worker.progress.connect(self.engine_progress.emit)
        self._load_worker.done.connect(self.engine_status.emit)
        self._load_worker.start()

    def set_angles(self, angles):
        if angles:
            self.rec.set_angles(tuple(angles))

    def set_targets(self, targets):
        self.decider.set_targets(targets)

    # ---------- 输入源 ----------
    def start_source(self, cfg: dict):
        self.stop_source()
        t = cfg["type"]
        if t == "camera":
            src = CameraSource(cfg["camera_index"], cfg["fps"])
        else:
            path = cfg["path"]
            loop = cfg["loop"] and t == "folder"
            src = FolderSource(path, cfg["interval_ms"], loop)
        src.frame_ready.connect(self._on_frame)
        src.read_failed.connect(self._on_read_failed)
        src.finished.connect(self.source_finished.emit)
        self.current_source = src
        src.start()

    def stop_source(self):
        if self.current_source:
            self.current_source.stop()
            self.current_source = None

    # ---------- 帧 → 推理 ----------
    def _on_frame(self, frame, name):
        self.frames_in += 1
        self.frame_ready.emit(frame, name)
        self.infer_worker.submit(frame, name)

    def _on_read_failed(self, name):
        """图片打不开 —— 它仍然是一张图，必须走完整条分发链。

        以前这里是 `if img is not None` 直接跳过：坏文件会静默消失，
        既不进历史、也不进 CSV、更不会给 Arduino 发信号。
        """
        self.frames_in += 1
        res = RecognitionResult(
            filename=name, status="read_failed",
            error_msg="图片无法读取（文件损坏或格式不支持）")
        self._on_result(res)
        self._ack_source()

    def _on_frame_processed(self, name: str = ""):
        self._ack_source()

    def _ack_source(self):
        """告诉输入源：这一帧处理完了，可以取下一帧。"""
        if self.current_source:
            self.current_source.frame_done()

    # ---------- 结果 → 决策 → 串口 → UI ----------
    def _on_result(self, res):
        # ★ 每张图都必须留下一条记录 + 一个串口字节
        self.results_out += 1

        # 1) UI 更新
        self.result_ready.emit(res)

        # 2) CSV
        if self.config["app"].get("save_csv", True):
            try:
                self.csv.write(res)
            except Exception as e:
                print("csv write error:", e)

        # 3) 串口：**不做「仅变化时发送」**
        #    固件是「收到一个 '1' 吹一次、收到 '0' 立刻关」，按帧发才能逐颗动作；
        #    若只在变化时发，连续两颗 NG 的第二颗就不会吹。
        if self.serial.is_open:
            ok, msg = self.serial.send_value(res.output_value)
            self.serial_sent.emit(res.output_value, ok, msg)

    # ---------- 串口 ----------
    def refresh_ports(self):
        return SerialService.list_ports()

    def open_serial(self, port: str, baud: int):
        return self.serial.open(port, baud)

    def close_serial(self):
        self.serial.close()

    # ---------- 对账 ----------
    @property
    def pending(self) -> int:
        """已收帧但还没出结果的帧数（正常应为 0 或 1）。"""
        return max(0, self.frames_in - self.results_out)

    # ---------- 退出 ----------
    def shutdown(self):
        self.stop_source()
        self.infer_worker.stop()
        self.serial.close()
        self.csv.close()
