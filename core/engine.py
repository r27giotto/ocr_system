import threading
import traceback

from paddlex import create_model


def detect_device() -> str:
    """有可用 CUDA 就 gpu:0，否则 cpu。换机器不用改配置。"""
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0"
    except Exception:
        pass
    return "cpu"


class EngineManager:
    """
    按模型名缓存 PaddleX 模型实例。
    同一模型名只加载一次；不同模型名各自缓存。
    """
    def __init__(self, device: str = "gpu:0"):
        """
        :param device: 推理设备，"gpu:0"/"gpu:1"/"cpu"，或 "auto"（自动探测）
        """
        if device in (None, "", "auto"):
            device = detect_device()
        self._device = device
        self._rec_cache: dict[str, object] = {}
        self._ori_cache: dict[str, object] = {}
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        """当前实际使用的设备（GPU 加载失败后会变成 "cpu"）。"""
        return self._device

    def _create(self, model_name: str, progress_cb=None):
        """加载模型；GPU 初始化失败时退回 CPU 再试一次。

        create_model 在 CUDA 初始化失败（驱动/显存/无卡）时会直接抛异常。
        换一台没装驱动的机器跑，与其整个界面起不来，不如慢一点用 CPU。
        """
        try:
            return create_model(model_name, device=self._device)
        except Exception:
            if not str(self._device).startswith("gpu"):
                raise
            traceback.print_exc()
            if progress_cb:
                progress_cb(f"{self._device} 加载 {model_name} 失败，改用 CPU 重试 …")
            self._device = "cpu"
            return create_model(model_name, device="cpu")

    def get_rec(self, model_name: str, progress_cb=None):
        with self._lock:
            if model_name not in self._rec_cache:
                if progress_cb:
                    progress_cb(f"加载识别模型 {model_name} 到 {self._device} …")
                self._rec_cache[model_name] = self._create(model_name, progress_cb)
            return self._rec_cache[model_name]

    def get_ori(self, model_name: str, progress_cb=None):
        with self._lock:
            if model_name not in self._ori_cache:
                if progress_cb:
                    progress_cb(f"加载方向模型 {model_name} 到 {self._device} …")
                self._ori_cache[model_name] = self._create(model_name, progress_cb)
            return self._ori_cache[model_name]

    def is_loaded(self, rec_name: str, ori_name: str) -> bool:
        return rec_name in self._rec_cache and ori_name in self._ori_cache
