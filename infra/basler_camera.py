# -*- coding: utf-8 -*-
"""Basler 相机（acA1300-60gm，GigE）取图封装，基于 pypylon。

两种用法，对应界面上两个按钮：

- **测试摄像头**：`mode="free"`，关掉硬件触发，自己连续取图 → 给预览窗显示。
- **开始**：`mode="trigger"`，打开硬件触发（`TriggerMode=On`），每来一个
  电眼信号出一张图。**不插电眼/不触发就一张也出不来**，这是正常现象。

`pypylon` 是**延迟导入**的：没装也不影响文件夹模式跑起来，只有真正用到相机
时才报错，报错信息直接告诉你去装什么。
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np


class CameraError(RuntimeError):
    """相机相关的可读错误（找不到相机、被占用、参数不支持…）。"""


def pylon_module():
    """延迟拿 `pypylon.pylon`；没装时抛出带安装提示的 CameraError。"""
    try:
        import pypylon.pylon as pylon  # noqa: WPS433 (延迟导入是有意的)
        return pylon
    except Exception as exc:  # pragma: no cover - 取决于环境
        raise CameraError(
            "没装 pypylon，无法使用摄像头模式。\n"
            "安装：uv pip install pypylon --python .venv\\Scripts\\python.exe\n"
            "原始错误：%s" % (exc,)
        ) from exc


def is_available() -> bool:
    try:
        pylon_module()
        return True
    except CameraError:
        return False


def enumerate_devices() -> List[str]:
    """返回所有可见 Basler 相机的全名；没有则返回空列表。"""
    pylon = pylon_module()
    try:
        factory = pylon.TlFactory.GetInstance()
        return [d.GetFullName() for d in factory.EnumerateDevices()]
    except Exception as exc:  # pragma: no cover - 取决于环境
        raise CameraError("枚举相机失败：%s" % (exc,)) from exc


class BaslerCamera:
    """一台相机。`open()` 之前不碰任何硬件。"""

    def __init__(self, config: Optional[dict] = None):
        cfg = dict(config or {})
        self.trigger_line = str(cfg.get("trigger_line", "Line1"))
        self.trigger_activation = str(cfg.get("trigger_activation", "RisingEdge"))
        # 触发源：`Line1` = 电眼接在相机的输入线上（生产用法）；
        # `Software` = 由软件调 `software_trigger()` 出图（没有电眼时联调用）。
        self.trigger_source = str(cfg.get("trigger_source", "Line1"))
        self.exposure_us = float(cfg.get("exposure_us", 2000))
        self.timeout_ms = int(cfg.get("timeout_ms", 1000))

        self._pylon = None
        self._cam = None
        self._lock = threading.Lock()
        self.warnings: List[str] = []
        self.device_name: Optional[str] = None

    # ---- 生命周期 ---------------------------------------------------------
    def open(self, mode: str = "trigger", serial: Optional[str] = None) -> None:
        """打开第一台（或指定 serial 的）相机并配置好。"""
        if mode not in ("trigger", "free"):
            raise CameraError("mode 只能是 'trigger' 或 'free'，收到 %r" % (mode,))
        self.close()
        pylon = self._pylon = pylon_module()
        self.warnings = []

        try:
            factory = pylon.TlFactory.GetInstance()
            devices = factory.EnumerateDevices()
            if not devices:
                raise CameraError(
                    "没有找到 Basler 相机。请检查：\n"
                    "1) 网线是否插在相机与网卡之间；2) 网卡是否设成与相机同网段；\n"
                    "3) 用 Pylon Viewer 能否看到并打开相机；\n"
                    "4) 相机是否正被 Pylon Viewer 或别的程序占用。"
                )
            info = devices[0]
            if serial:
                for d in devices:
                    if d.GetSerialNumber() == serial:
                        info = d
                        break
            self.device_name = info.GetFullName()
            cam = pylon.InstantCamera(factory.CreateDevice(info))
            cam.Open()
            self._cam = cam
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError("打开相机失败：%s" % (exc,)) from exc

        self._apply_exposure()
        if mode == "trigger":
            self._apply_trigger()
        else:
            self._set("TriggerMode", "Off", "关闭硬件触发（测试模式）")
        self._start_grabbing()

    def _start_grabbing(self) -> None:
        pylon = self._pylon
        try:
            self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly,
                                    pylon.GrabLoop_ProvidedByUser)
        except Exception as exc:
            self.close()
            raise CameraError("启动取流失败：%s" % (exc,)) from exc

    def close(self) -> None:
        with self._lock:
            cam, self._cam = self._cam, None
            if cam is None:
                return
            try:
                if cam.IsGrabbing():
                    cam.StopGrabbing()
            except Exception:
                pass
            try:
                if cam.IsOpen():
                    cam.Close()
            except Exception:
                pass

    # ---- 取图 -------------------------------------------------------------
    def grab(self, timeout_ms: Optional[int] = None) -> Optional[np.ndarray]:
        """等一张图。超时/无触发返回 None（这是正常情况，不是错误）。"""
        with self._lock:
            cam = self._cam
            pylon = self._pylon
        if cam is None:
            return None
        wait = self.timeout_ms if timeout_ms is None else int(timeout_ms)
        try:
            result = cam.RetrieveResult(wait, pylon.TimeoutHandling_Return)
        except Exception as exc:
            raise CameraError("取图失败：%s" % (exc,)) from exc
        if result is None:
            return None
        try:
            if not result.GrabSucceeded():
                return None
            # 必须拷贝：pypylon 的数组指向会被下一次取图复用的缓冲区
            return _to_bgr(result.GetArray().copy(), result.GetPixelType())
        finally:
            try:
                result.Release()
            except Exception:
                pass

    # ---- 配置项（不支持的特性只记警告，不中断）----------------------------
    def _set(self, feature: str, value, what: str) -> None:
        cam = self._cam
        try:
            node = getattr(cam, feature)
            node.Value = value
        except Exception as exc:
            self.warnings.append("%s：相机不支持 %s=%r（%s）" % (what, feature, value, exc))

    def _apply_exposure(self) -> None:
        cam = self._cam
        try:
            cam.ExposureAuto.Value = "Off"
        except Exception:
            pass
        try:
            cam.ExposureTime.SetValue(self.exposure_us)
        except Exception as exc:
            self.warnings.append("设置曝光 %gus 失败：%s" % (self.exposure_us, exc))

    def _apply_trigger(self) -> None:
        self._set("TriggerSelector", "FrameStart", "硬件触发")
        self._set("TriggerMode", "On", "硬件触发")
        self._set("TriggerSource", self.trigger_source, "硬件触发")
        if self.trigger_source != "Software":
            # `TriggerActivation` 只对硬件输入线有意义，软件触发下设它多半报「不支持」
            self._set("TriggerActivation", self.trigger_activation, "硬件触发")

    def software_trigger(self) -> bool:
        """手动发一次触发（仅 `TriggerSource=Software` 时有效）。

        用于没有电眼时联调：调一次就出一张图。失败抛 `CameraError`。
        """
        cam = self._cam
        if cam is None:
            return False
        try:
            cam.ExecuteSoftwareTrigger()
            return True
        except Exception as exc:
            raise CameraError(
                "软件触发失败：%s\n（相机需要是 TriggerSource=Software）" % (exc,)
            ) from exc


def _to_bgr(arr: np.ndarray, pixel_type=None) -> np.ndarray:
    """把相机原始像素转成 3 通道 BGR（后续预处理统一吃 BGR）。"""
    if arr.ndim == 2:
        arr = _stretch_to_8bit(arr)
        return np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return arr[:, :, :3].copy()
    if arr.ndim == 3 and arr.shape[2] == 3:
        # pypylon 对彩色机型给的是 RGB，流水线要 BGR
        return arr[:, :, ::-1].copy()
    raise CameraError("不认识的图像形状：%r" % (arr.shape,))


def _stretch_to_8bit(arr: np.ndarray) -> np.ndarray:
    """Mono12/16 拉到 0-255；已经是 8 位的原样返回。"""
    if arr.dtype == np.uint8:
        return arr
    lo, hi = float(arr.min()), float(arr.max())
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (arr.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return scaled.clip(0, 255).astype(np.uint8)
