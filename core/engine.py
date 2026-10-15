import threading
from paddlex import create_model

class EngineManager:
    """
    按模型名缓存 PaddleX 模型实例。
    同一模型名只加载一次；不同模型名各自缓存。
    """
    def __init__(self):
        self._rec_cache: dict[str, object] = {}
        self._ori_cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def get_rec(self, model_name: str, progress_cb=None):
        with self._lock:
            if model_name not in self._rec_cache:
                if progress_cb:
                    progress_cb(f"加载识别模型 {model_name} …")
                self._rec_cache[model_name] = create_model(model_name)
            return self._rec_cache[model_name]

    def get_ori(self, model_name: str, progress_cb=None):
        with self._lock:
            if model_name not in self._ori_cache:
                if progress_cb:
                    progress_cb(f"加载方向模型 {model_name} …")
                self._ori_cache[model_name] = create_model(model_name)
            return self._ori_cache[model_name]

    def is_loaded(self, rec_name: str, ori_name: str) -> bool:
        return rec_name in self._rec_cache and ori_name in self._ori_cache