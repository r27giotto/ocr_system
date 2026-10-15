import time
import cv2
import numpy as np

from core.decision import DecisionMaker
from core.models import RecognitionResult
from core.preprocess import Preprocessor
from core.recognizer import Recognizer


class OcrPipeline:
    def __init__(self, pre: Preprocessor, rec: Recognizer,
                 decider: DecisionMaker):
        self.pre = pre
        self.rec = rec
        self.decider = decider

    def run_on_image(self, img: np.ndarray,
                     filename: str = "") -> RecognitionResult:
        t0 = time.perf_counter()
        res = RecognitionResult(filename=filename, frame=img.copy())

        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            enhanced = self.pre.enhance(gray)
            crop = self.pre.find_roi(enhanced)

            if crop is None:
                res.status = "circle_not_found"
                return self._finish(res, t0)

            roi, (cx, cy, r), (x1, y1, x2, y2) = crop
            res.roi_box = (int(x1), int(y1), int(x2), int(y2))

            best = self.rec.recognize(roi)
            if best is None:
                res.status = "no_number"
                return self._finish(res, t0)

            num, conf, angle = best
            res.number = num
            res.confidence = round(conf, 4)
            res.angle = angle
            res.hit = self.decider.is_hit(num)
            res.output_value = self.decider.decide(num)
            res.status = "ok"

        except Exception as e:
            res.status = "error"
            res.error_msg = str(e)

        return self._finish(res, t0)

    @staticmethod
    def _finish(res: RecognitionResult, t0: float) -> RecognitionResult:
        res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return res