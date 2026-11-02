"""兼容层：真正的实现搬到了 `core/render.py`（纯 cv2，不依赖 Qt），
这样 `app/controller.py` 存结果图时不必反过来 import `ui.*`。

老的 `from ui.overlay import draw_overlay` 写法继续可用。
"""
from core.render import draw_overlay  # noqa: F401

__all__ = ["draw_overlay"]
