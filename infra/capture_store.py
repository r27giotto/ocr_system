# -*- coding: utf-8 -*-
"""相机模式下的图片落盘：每次「开始」建一个时间戳子文件夹，两个根目录各滚一份。

目录形态（`storage:` 里的两个根，来自 `config.yaml`）：

    logs/captures_raw/20261019_143012/000001.png   ← 相机原图，未叠任何东西
    logs/captures_result/20261019_143012/000001.png ← 带框 + 数字 + 置信度

两个子文件夹用**同一个时间戳**，所以一眼能对上「这张图的结果图是哪张」。

滚动上限 `max_images` 是**跨所有会话**的总数：超过就删最旧的图片文件，删完
顺手把空掉的会话文件夹也删掉。这样磁盘占用是有界的，而不是每开一次就多一堆。

为什么不用 `cv2.imwrite`：它在 Windows 上遇到非 ASCII 路径会静默失败
（返回 False，不抛异常）。这里统一走 `cv2.imencode` + `tofile`，路径怎么写都行。
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Optional, Tuple

import cv2
import numpy as np

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
_SESSION_RE = re.compile(r"^\d{8}_\d{6}(?:_\d+)?$")


class CaptureStore:
    def __init__(self, raw_root: str, result_root: str, max_images: int = 10):
        self.raw_root = raw_root
        self.result_root = result_root
        self.max_images = max(1, int(max_images))
        self._lock = threading.Lock()
        self._raw_dir: Optional[str] = None
        self._result_dir: Optional[str] = None
        self._seq = 0

    # ---- 会话 -------------------------------------------------------------
    def new_session(self, when: Optional[datetime] = None) -> Tuple[str, str]:
        """建一对新的时间戳子文件夹，后续 `save()` 都会写进这对。"""
        stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
        with self._lock:
            name = stamp
            n = 2
            while True:
                raw_dir = os.path.join(self.raw_root, name)
                result_dir = os.path.join(self.result_root, name)
                if not os.path.exists(raw_dir) and not os.path.exists(result_dir):
                    break
                name = "%s_%d" % (stamp, n)
                n += 1
            os.makedirs(raw_dir, exist_ok=True)
            os.makedirs(result_dir, exist_ok=True)
            self._raw_dir, self._result_dir = raw_dir, result_dir
            self._seq = 0
            return raw_dir, result_dir

    @property
    def session_name(self) -> Optional[str]:
        return os.path.basename(self._raw_dir) if self._raw_dir else None

    # ---- 落盘 -------------------------------------------------------------
    def save(self, raw_bgr: np.ndarray,
             result_bgr: Optional[np.ndarray] = None) -> Tuple[str, Optional[str]]:
        """存一张原图（+ 可选的结果图），返回实际写入的路径。"""
        if self._raw_dir is None:
            self.new_session()
        with self._lock:
            self._seq += 1
            fname = "%06d.png" % self._seq
            raw_path = os.path.join(self._raw_dir, fname)
            result_path = None
            _write_png(raw_path, raw_bgr)
            if result_bgr is not None and self._result_dir:
                result_path = os.path.join(self._result_dir, fname)
                _write_png(result_path, result_bgr)
        self.prune()
        return raw_path, result_path

    def reset_seq(self) -> None:
        with self._lock:
            self._seq = 0

    # ---- 滚动 -------------------------------------------------------------
    def prune(self) -> int:
        """两个根目录各自保留最新的 `max_images` 张，返回删除的文件数。"""
        removed = 0
        for root in (self.raw_root, self.result_root):
            removed += _prune_root(root, self.max_images)
        return removed

    def count(self, root: Optional[str] = None) -> int:
        return len(_list_images(root or self.raw_root))


# ---- 内部工具 -------------------------------------------------------------
def _write_png(path: str, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise IOError("PNG 编码失败：%s" % path)
    tmp = path + ".tmp"
    buf.tofile(tmp)
    os.replace(tmp, path)


def _list_images(root: str) -> list:
    """按「会话名 + 文件名」升序返回所有图片路径（旧的在前）。"""
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        sub = os.path.join(root, name)
        if os.path.isdir(sub):
            if not _SESSION_RE.match(name):
                continue
            for fn in sorted(os.listdir(sub)):
                if fn.lower().endswith(IMG_EXTS):
                    out.append(os.path.join(sub, fn))
        elif name.lower().endswith(IMG_EXTS):
            out.append(sub)
    return out


def _prune_root(root: str, max_images: int) -> int:
    files = _list_images(root)
    if len(files) <= max_images:
        return 0
    removed = 0
    for path in files[:len(files) - max_images]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            continue
        _drop_empty_session(os.path.dirname(path), root)
    return removed


def _drop_empty_session(session_dir: str, root: str) -> None:
    try:
        if os.path.abspath(session_dir) == os.path.abspath(root):
            return
        if os.path.isdir(session_dir) and not os.listdir(session_dir):
            os.rmdir(session_dir)
    except OSError:
        pass
