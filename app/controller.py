from PyQt6.QtCore import QObject, pyqtSignal

from core.engine import EngineManager
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
    engine_status = pyqtSignal(bool, str)
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
        self.infer_worker.start()

        # ---- 状态 ----
        self.current_source = None
        self._last_sent_value = None
        self._send_on_change_only = False

    # ---------- 模型 ----------
    def load_models(self, rec_name: str, ori_name: str):
        self.rec.set_models(rec_name, ori_name)
        self._load_worker = EngineLoadWorker(self.engine, rec_name, ori_name)
        self._load_worker.progress.connect(
            lambda s: self.engine_status.emit(False, s))
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
        src.finished.connect(self.source_finished.emit)
        self.current_source = src
        src.start()

    def stop_source(self):
        if self.current_source:
            self.current_source.stop()
            self.current_source = None

    # ---------- 帧 → 推理 ----------
    def _on_frame(self, frame, name):
        self.frame_ready.emit(frame, name)
        self.infer_worker.submit(frame, name)

    # ---------- 结果 → 决策 → 串口 → UI ----------
    def _on_result(self, res):
        # 1) UI 更新
        self.result_ready.emit(res)

        # 2) CSV
        if self.config["app"].get("save_csv", True):
            try:
                self.csv.write(res)
            except Exception as e:
                print("csv write error:", e)

        # 3) 串口
        if self.serial.is_open:
            if (not self._send_on_change_only
                    or res.output_value != self._last_sent_value):
                ok, msg = self.serial.send_value(res.output_value)
                if ok:
                    self._last_sent_value = res.output_value
                self.serial_sent.emit(res.output_value, ok, msg)

    def set_send_on_change_only(self, v: bool):
        self._send_on_change_only = bool(v)
        if not v:
            self._last_sent_value = None

    # ---------- 串口 ----------
    def refresh_ports(self):
        return SerialService.list_ports()

    def open_serial(self, port: str, baud: int):
        return self.serial.open(port, baud)

    def close_serial(self):
        self.serial.close()

    # ---------- 退出 ----------
    def shutdown(self):
        self.stop_source()
        self.infer_worker.stop()
        self.serial.close()
        self.csv.close()