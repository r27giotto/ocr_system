import traceback

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
    engine_status = pyqtSignal(bool, str, str)   # 终态：(是否成功, 消息, 模型名)
    engine_progress = pyqtSignal(str)       # 过程：正在加载哪个模型
    # ★ 引擎忙（正在加载模型）。加载期间「开始」必须按不下去：
    #   加载线程持着 EngineManager 的锁，而推理线程第一件事就是拿这把锁，
    #   这时候开跑等于把检测线程堵在加载器后面。
    engine_busy = pyqtSignal(bool)
    source_finished = pyqtSignal()
    # ★ 输入源是否在跑。UI 的「开始/停止」按钮只认这一个信号，
    #   因为「回到空闲」有 4 条路径（自然跑完 / 手动停止 / 空文件夹 /
    #   源启动失败），以前只有第 1 条会通知界面，手动停止后按钮就一直灰着。
    source_state = pyqtSignal(bool)          # True=运行中, False=空闲
    source_error = pyqtSignal(str)           # 输入源启动失败（如路径不存在）

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

        # ---- 核心层 ----
        # 设备由 config.yaml 的 engine.device 决定：auto / cpu / gpu:0
        self.engine = EngineManager(config.get("engine", {}).get("device", "auto"))
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
        self._source_running = False
        # ★ 引擎状态：只有**加载成功**才把模型名交给 Recognizer。
        #   以前在 load_models() 开头就 set_models()，加载一失败，
        #   rec_model_name 已经是新名字，之后每帧都抛
        #   `No engine bindings registered for model '<名>'`。
        self._loading = False
        self._loaded = (None, None)      # (rec_name, ori_name)，仅加载成功时写
        self._load_worker = None
        # ★ 对账计数器：进来的帧数 vs 出去的结果数。
        #   两者相等 = 每张图都处理到了；不等就说明有帧卡在队列里。
        self.frames_in = 0
        self.results_out = 0

    # ---------- 模型 ----------
    @property
    def models_ready(self) -> bool:
        """模型是否已加载好（可以直接开跑）。"""
        return self._loaded[0] is not None

    @property
    def engine_loading(self) -> bool:
        return self._loading

    def load_models(self, rec_name: str, ori_name: str):
        """异步加载。**运行中不允许加载** —— 加载线程会持 `EngineManager` 的
        锁几秒，而推理线程每帧都要拿这把锁，开了就是卡住检测线。
        """
        if self._source_running:
            self.engine_status.emit(
                False, "检测正在运行，请先点「停止」再加载模型", rec_name)
            return
        if self._loading:
            self.engine_status.emit(False, "模型正在加载中，请稍候", rec_name)
            return

        self._loading = True
        self.engine_busy.emit(True)
        self._load_worker = EngineLoadWorker(self.engine, rec_name, ori_name)
        # 进度和终态必须走两条信号：engine_status 带 ok 布尔，
        # 之前把进度也塞进它（ok=False），界面就把「正在加载 X」当成「加载失败」。
        self._load_worker.progress.connect(self.engine_progress.emit)
        self._load_worker.done.connect(
            lambda ok, msg: self._on_load_done(ok, msg, rec_name, ori_name))
        self._load_worker.start()

    def _on_load_done(self, ok: bool, msg: str, rec_name: str, ori_name: str):
        self._loading = False
        if ok:
            # ★ 只有这一刻才让 Recognizer 认新模型名
            self.rec.set_models(rec_name, ori_name)
            self._loaded = (rec_name, ori_name)
        self.engine_busy.emit(False)
        self.engine_status.emit(ok, msg, rec_name)

    def mark_models_loaded(self, rec_name: str, ori_name: str = ""):
        """假定模型已经就绪（**给测试/自检用**，正常运行流程不调用它）。"""
        self._loading = False
        self.rec.set_models(rec_name, ori_name)
        self._loaded = (rec_name, ori_name)

    def set_angles(self, angles):
        if angles:
            self.rec.set_angles(tuple(angles))

    def set_targets(self, targets):
        self.decider.set_targets(targets)

    # ---------- 输入源 ----------
    def start_source(self, cfg: dict):
        # ★ 引擎没就绪就别开跑：这时推理线程拿不到模型，
        #   只会对每一帧报 `No engine bindings registered for model '…'`。
        #   界面在按钮点下时已先置「运行中」，所以这里必须无条件回一次「空闲」。
        if self._loading:
            self.source_state.emit(False)
            self.source_error.emit("模型正在加载，请等加载完成再开始")
            return
        if not self.models_ready:
            self.source_state.emit(False)
            self.source_error.emit("模型未加载，请先点「加载模型」")
            return

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
        # 把 src 绑给处理器：旧摄像头线程 stop() 之后可能还补发一次 finished，
        # 那一次绝不能把**新一轮**的运行状态关掉（_on_source_finished 会丢弃）。
        src.finished.connect(lambda s=src: self._on_source_finished(s))
        self.current_source = src
        # 先置「运行中」再 start()：空文件夹会在 start() 里同步发 finished，
        # 先置位才能让那一次 finished 把状态正确落回空闲。
        self._set_source_state(True)
        try:
            src.start()
        except Exception as e:
            # 路径不存在 / 摄像头参数非法等：必须退回空闲，否则「开始」永远灰着
            traceback.print_exc()
            self.current_source = None
            self._set_source_state(False)
            self.source_error.emit(str(e))

    def stop_source(self):
        src, self.current_source = self.current_source, None
        if src is None:
            return
        # 先落回空闲再 stop()：摄像头 stop 要等读帧线程退出（最多 2s），
        # 这段时间界面不该还显示「运行中」。
        self._set_source_state(False)
        src.stop()

    def _set_source_state(self, running: bool):
        """状态只在**变化**时才发信号，避免开始→停止连着来时界面闪一下。"""
        if running == self._source_running:
            return
        self._source_running = running
        self.source_state.emit(running)

    def _on_source_finished(self, src):
        """输入源自己跑完了：放完一遍 / 空文件夹 / 摄像头打不开。"""
        if src is not self.current_source:
            return                  # 已被替换或已手动停止的旧源，忽略
        self.current_source = None
        self.source_finished.emit()
        self._set_source_state(False)

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
