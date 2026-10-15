import csv
import threading
from pathlib import Path

from core.models import RecognitionResult


class CsvLogger:
    FIELDS = ["timestamp", "filename", "number", "confidence", "angle",
              "hit", "output_value", "status", "elapsed_ms"]

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fp = open(self.path, "w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._fp, fieldnames=self.FIELDS)
        self._writer.writeheader()
        self._fp.flush()

    def write(self, res: RecognitionResult):
        with self._lock:
            self._writer.writerow({
                "timestamp": f"{res.timestamp:.3f}",
                "filename": res.filename,
                "number": res.number,
                "confidence": res.confidence,
                "angle": res.angle,
                "hit": res.hit,
                "output_value": res.output_value,
                "status": res.status,
                "elapsed_ms": res.elapsed_ms,
            })
            self._fp.flush()

    def close(self):
        with self._lock:
            if self._fp and not self._fp.closed:
                self._fp.close()