import cv2
import numpy as np

from core.models import RecognitionResult


def draw_overlay(img: np.ndarray, res: RecognitionResult) -> np.ndarray:
    """在图像上画 ROI 框 + 识别数字 + 置信度 + 决策结果"""
    vis = img.copy()

    if res.status != "ok" or not res.roi_box:
        cv2.putText(vis, res.status, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return vis

    x1, y1, x2, y2 = res.roi_box
    # 配色与 ResultPanel 一致：G=绿，NG=红（BGR）
    color = (0, 200, 0) if res.output_text == "G" else (0, 0, 255)

    cv2.rectangle(vis, (x1, y1), (x2, y2), color, 4)

    label = f"{res.number} | {res.confidence:.2f} | {res.output_text}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    ly = y1 - 10 if y1 - 10 - th > 0 else y2 + th + 10
    cv2.rectangle(vis, (x1, ly - th - 4), (x1 + tw + 8, ly + 4),
                  (255, 255, 255), -1)
    cv2.putText(vis, label, (x1 + 4, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    # 右上角大号判定结果（"NG" 比单个字符宽，所以按实际文字宽度右对齐）
    big = res.output_text
    (bw, bh), _ = cv2.getTextSize(big, cv2.FONT_HERSHEY_SIMPLEX, 2.0, 4)
    cv2.putText(vis, big, (max(4, vis.shape[1] - bw - 16), 60 + bh // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, color, 4)

    return vis