import os
import traceback
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal

from core.engine import EngineManager
from core.models import RecognitionResult
from core.preprocess import Preprocessor, PreprocessConfig
from core.recognizer import Recognizer, RecognizerConfig
from core.decision import DecisionMaker
from core.pipeline import OcrPipeline
from infra.serial_service import SerialService
from infra.csv_logger import CsvLogger
from infra.capture_store import CaptureStore
from infra.image_source import FolderSource, CameraSource
from core.render import draw_overlay

from app.workers import EngineLoadWorker, InferenceWorker, CameraWorker


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
    # ---- 相机模式 ----
    preview_ready = pyqtSignal(object)       # 「测试摄像头」的预览帧（不进推理）
    camera_status = pyqtSignal(str)          # 相机面板上那行状态文字
    # 提示信息（不阻断、只写状态栏）：本次会话 CSV 写到哪、写失败等。
    # 不能用 source_error —— 那个在摄像头模式会弹窗，而这里只是「顺带没写成」。
    notice = pyqtSignal(str)

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
        # ---- 相机 ----
        # 「测试摄像头」点过且真的开出了图，「开始」才允许拍。
        # 只点一次就够，之后重复开始/停止不再要求重测；相机一报错就作废。
        self.camera_tested = False
        self._preview_worker = None
        self.capture_store = None
        # 本次运行的 CSV（一次运行一份，跟着运行起止开合）
        self._session_csv = None
        self.session_csv_path = None
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

    # ---------- 相机 ----------
    def test_camera(self, cfg: dict = None):
        """「测试摄像头」：开相机连续取图，只显示在预览区，不进推理、不落盘。"""
        self.stop_source()
        self._stop_preview()
        self.camera_tested = False
        self.camera_status.emit("正在打开相机…")
        worker = CameraWorker(self.config.get("camera", {}), mode="preview",
                              preview_fps=10)
        worker.preview.connect(self.preview_ready.emit)
        worker.opened.connect(self._on_camera_opened)
        worker.error.connect(self._on_camera_error)
        worker.warn.connect(self.camera_status.emit)
        self._preview_worker = worker
        worker.start()

    def _stop_preview(self):
        worker, self._preview_worker = self._preview_worker, None
        if worker is None:
            return
        try:
            worker.preview.disconnect()      # 别让残留帧盖掉正在跑的检测画面
        except Exception:
            pass
        worker.stop()

    @property
    def previewing(self) -> bool:
        return self._preview_worker is not None

    def _on_camera_opened(self, name: str):
        self.camera_tested = True
        self.camera_status.emit("已连接：%s（预览中，点「开始」开拍）" % (name,))

    def _on_camera_error(self, msg: str):
        self.camera_tested = False
        self.camera_status.emit("相机不可用")
        self.source_error.emit(msg)

    def _make_camera_source(self):
        """建 CaptureStore + 新会话，返回待启动的取图线程。"""
        storage = self.config.get("storage", {})
        raw_dir = storage.get("capture_raw_dir", "./logs/captures_raw")
        result_dir = storage.get("capture_result_dir", "./logs/captures_result")
        max_keep = self.config.get("camera", {}).get("max_saved_images", 10)
        try:
            self.capture_store = CaptureStore(raw_dir, result_dir, max_keep)
            raw_path, result_path = self.capture_store.new_session()
        except OSError as e:
            traceback.print_exc()
            self.capture_store = None
            self.source_error.emit("建落盘目录失败：%s" % (e,))
            return None
        self.camera_status.emit("开拍中，存到 %s" % (raw_path,))
        print("[camera] 原图 ->", raw_path)
        print("[camera] 结果 ->", result_path)
        # 本次运行的 CSV 就放在「识别历史」那棵树里，跟 PNG 同目录
        self._open_session_csv(
            self._session_csv_target("camera", "", result_path))
        worker = CameraWorker(self.config.get("camera", {}), mode="capture",
                              store=self.capture_store)
        worker.error.connect(self._on_camera_error)
        worker.warn.connect(self.camera_status.emit)
        return worker

    # ---------- 本次运行的 CSV ----------
    def _session_csv_target(self, kind: str, path: str,
                            result_dir: str = None) -> str:
        """算出「本次运行」的 CSV 路径。

        - 摄像头：`<识别历史>/<时间戳>/results.csv`，和那批带框图放一起
        - 文件夹：`<所选文件夹>/results_<时间戳>.csv`
        - 单图  ：`<图片所在目录>/results_<时间戳>.csv`
        """
        if kind == "camera" and result_dir:
            return os.path.join(result_dir, "results.csv")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.dirname(os.path.abspath(path)) if kind == "single" \
            else os.path.abspath(path)
        return os.path.join(folder, "results_%s.csv" % (stamp,))

    def _open_session_csv(self, target: str):
        """开一份新的会话 CSV。写不进去**不阻断运行**，只在状态栏说一声 ——
        全局总账还会照写，不至于一张记录都不留。"""
        self._close_session_csv()
        try:
            self._session_csv = CsvLogger(target, mode="w")
            self.session_csv_path = target
            self.notice.emit("本次记录已开：%s" % (target,))
        except Exception as e:
            self._session_csv = None
            self.session_csv_path = None
            traceback.print_exc()
            self.notice.emit("本次运行的 CSV 写不了（只记全局那份）：%s" % (e,))

    def _close_session_csv(self):
        if self._session_csv is not None:
            try:
                self._session_csv.close()
            except Exception:
                pass
            self._session_csv = None
        self.session_csv_path = None

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
            # ★ 用户的硬要求：点「开始」前必须先点过「测试摄像头」。
            #   没测过就直接开拍的话，现场没法区分「没有工件」和「相机没配好」。
            if not self.camera_tested:
                self.source_state.emit(False)
                self.source_error.emit(
                    "摄像头还没测过：请先点「测试摄像头」确认能出图，"
                    "再点「开始」。")
                return
            self._stop_preview()      # 同一台相机不能被两个线程同时占着
            src = self._make_camera_source()
            if src is None:
                self.source_state.emit(False)
                return
        else:
            path = cfg["path"]
            loop = cfg["loop"] and t == "folder"
            src = FolderSource(path, cfg["interval_ms"], loop)
            # 文件 / 单图模式：CSV 直接落到所选目录（单图则落到图片所在目录）
            self._open_session_csv(self._session_csv_target(t, path))
        src.frame_ready.connect(self._on_frame)
        # 只有文件类输入源会发 read_failed；相机线程没有这个信号
        if hasattr(src, "read_failed"):
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
            self._close_session_csv()
            self._set_source_state(False)
            self.source_error.emit(str(e))

    def stop_source(self):
        src, self.current_source = self.current_source, None
        if src is None:
            self._close_session_csv()
            return
        # 先落回空闲再 stop()：摄像头 stop 要等读帧线程退出（最多 2s），
        # 这段时间界面不该还显示「运行中」。
        self._set_source_state(False)
        src.stop()
        self._close_session_csv()

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
        # 自然跑完也要收尾：把本次运行的 CSV 关掉（否则下次「开始」才发现没关）
        self._close_session_csv()
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

        # 2) CSV —— 写两份：全局总账（追加，跨运行积累）+ 本次运行的会话表
        if self.config["app"].get("save_csv", True):
            for logger in (self.csv, self._session_csv):
                if logger is None:
                    continue
                try:
                    logger.write(res)
                except Exception as e:
                    print("csv write error:", e)

        # 3) 相机模式：原图 + 带框结果图各存一份到本次会话的时间戳目录
        #    `res.frame` 是整帧原因，所以这里能同时还原出「原图」和「结果图」。
        if self.capture_store is not None and res.frame is not None:
            try:
                self.capture_store.save(res.frame, draw_overlay(res.frame, res))
            except Exception as e:
                print("capture save error:", e)
                traceback.print_exc()

        # 4) 串口：**不做「仅变化时发送」**
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
        self._stop_preview()
        self._close_session_csv()
        self.capture_store = None
        self.infer_worker.stop()
        self.serial.close()
        self.csv.close()
