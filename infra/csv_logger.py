import csv
import threading
from datetime import datetime
from pathlib import Path

from core.models import RecognitionResult


class CsvLogger:
    """把识别结果写成 CSV（一份全局总账 + 每次运行一份会话表）。

    ★ 表头一律写**中文**（用户要求，m04905）。内部取值仍用 `FIELDS` 里的英文
    字段名，二者通过 `_HEADER_OF` 对应，所以改表头文案不会动到任何调用方。
    """

    #: 内部字段名 —— 程序里按它取值，**不要改**
    FIELDS = ["timestamp", "filename", "number", "confidence", "angle",
              "hit", "output_value", "status", "elapsed_ms"]

    #: 写进文件的中文表头，顺序与 `FIELDS` 一一对应
    HEADERS = ["时间戳", "文件名", "识别数字", "置信度", "角度",
               "命中目标", "判定值", "状态", "耗时(毫秒)"]

    #: 内部字段名 -> 中文表头
    _HEADER_OF = dict(zip(FIELDS, HEADERS))

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

        # 老文件是英文表头（v2.1 之前写的）。直接往后追加会让同一个文件里出现
        # 两种表头 —— 先把它留档，再原地把表头换成中文（数据行原样保留）。
        if not fresh and not self._header_matches():
            self._migrate_english_header()

        if fresh:
            # 只有清空重写才用 utf-8-sig 写 BOM（Excel 认中文）；追加用纯 utf-8，
            # 否则 BOM 会被塞进文件中间。
            self._fp = open(self.path, "w", newline="", encoding="utf-8-sig")
        else:
            self._fp = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fp, fieldnames=self.HEADERS)
        if fresh:
            self._writer.writeheader()
        self._fp.flush()

    def _migrate_english_header(self) -> bool:
        """把「英文表头」的老文件原地改成中文表头，数据行一条不动。

        ★ 故意**不用** `os.replace` 改名：`logs/results.csv` 常被别的进程占着
        （运行中的程序实例一直开着它），改名会 `WinError 32 另一个程序正在使用
        此文件`。改成「先复制一份 .bak，再原地重写」，只依赖写权限，实测可行。
        """
        backup = self.path.with_name(
            "%s.bak-%s%s" % (self.path.stem,
                             datetime.now().strftime("%Y%m%d-%H%M%S"),
                             self.path.suffix))
        try:
            with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except (OSError, UnicodeDecodeError):
            return False
        if not rows:
            return False
        try:
            with open(backup, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(rows)
        except OSError:
            return False           # 备份写不出来就不动原文件，宁可追加也不冒险
        try:
            with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.HEADERS)
                for row in rows[1:]:      # 老表头丢掉，数据行照抄
                    w.writerow(row)
        except OSError:
            return False
        return True

    def _header_matches(self) -> bool:
        """现有文件的第一行是不是我们期望的中文表头。"""
        try:
            with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
                row = next(csv.reader(f), None)
        except (OSError, UnicodeDecodeError):
            return False
        return row == self.HEADERS

    def write(self, res: RecognitionResult):
        with self._lock:
            row = {
                "timestamp": f"{res.timestamp:.3f}",
                "filename": res.filename,
                "number": res.number,
                "confidence": res.confidence,
                "angle": res.angle,
                "hit": res.hit,
                "output_value": res.output_value,
                "status": res.status,
                "elapsed_ms": res.elapsed_ms,
            }
            self._writer.writerow(
                {self._HEADER_OF[k]: v for k, v in row.items()})
            self._fp.flush()

    def close(self):
        with self._lock:
            if self._fp and not self._fp.closed:
                self._fp.close()
