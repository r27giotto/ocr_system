import csv
import threading
from pathlib import Path

from core.models import RecognitionResult


class CsvLogger:
    FIELDS = ["timestamp", "filename", "number", "confidence", "angle",
              "hit", "output_value", "status", "elapsed_ms"]

    def __init__(self, path: str, mode: str = "a"):
        """`mode="a"` 追加（默认，给全局总账用）；`mode="w"` 覆盖（给「每次运行
        一份」的会话表用 —— 那份文件本来就是一次运行一份，覆盖是对的）。

        ★ 以前一律用 `"w"`：程序每启动一次就把 `logs/results.csv` 清空，
        上一次的记录全没了。改成追加后，表头只在文件**新建或为空**时写一次，
        否则追加会在文件中间再插一行表头。
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # 要不要写表头？新建、空文件、以及覆盖模式（"w" 会先清空）都要写。
        fresh = (mode == "w") or (not self.path.exists()) \
            or self.path.stat().st_size == 0
        if fresh:
            # 只有清空重写才用 utf-8-sig 写 BOM（Excel 认中文）；追加用纯 utf-8，
            # 否则 BOM 会被塞进文件中间。
            self._fp = open(self.path, "w", newline="", encoding="utf-8-sig")
        else:
            self._fp = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fp, fieldnames=self.FIELDS)
        if fresh:
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