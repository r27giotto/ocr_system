import csv
import threading
from datetime import datetime
from pathlib import Path

from core.models import RecognitionResult


def format_time(ts: float) -> str:
    """Unix 秒 -> `2026-11-02 11:47:10.123`（本地时间，精确到毫秒）。"""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _to_time_text(value: str) -> str:
    """把历史文件里的「Unix 秒」列换成可读时间；已经是时间字符串的原样返回。"""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return value
    return format_time(ts)


class CsvLogger:
    """把识别结果写成 CSV（一份全局总账 + 每次运行一份会话表）。

    ★ 表头一律写**中文**（用户要求，m04905）；**时间列是可读时间、精确到毫秒**
    （m05032），不再写 Unix 秒。内部取值仍用 `FIELDS` 里的英文字段名，二者通过
    `_HEADER_OF` 对应，所以改表头文案不会动到任何调用方。
    """

    #: 内部字段名 —— 程序里按它取值，**不要改**
    FIELDS = ["timestamp", "filename", "number", "confidence", "angle",
              "hit", "output_value", "status", "elapsed_ms"]

    #: 写进文件的中文表头，顺序与 `FIELDS` 一一对应
    HEADERS = ["时间", "文件名", "识别数字", "置信度", "角度",
               "命中目标", "判定值", "状态", "耗时(毫秒)"]

    #: 内部字段名 -> 中文表头
    _HEADER_OF = dict(zip(FIELDS, HEADERS))

    #: 能识别的历史表头（遇到就走迁移）。迁移时第 1 列的 Unix 秒会转成可读时间。
    _LEGACY_HEADERS = [
        # v2.2：中文表头，但时间列是 Unix 秒
        ["时间戳", "文件名", "识别数字", "置信度", "角度",
         "命中目标", "判定值", "状态", "耗时(毫秒)"],
        # v2.1 及更早：英文表头
        ["timestamp", "filename", "number", "confidence", "angle",
         "hit", "output_value", "status", "elapsed_ms"],
    ]

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

        # 老文件的表头不是当前这套。直接往后追加会让同一个文件里出现两种表头，
        # 所以先留档、再原地升级（表头 + 时间列一起转）。
        if not fresh and not self._header_matches():
            self._migrate_old_file()

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

    def _migrate_old_file(self) -> bool:
        """把老文件原地升级到当前格式：换表头 + 第 1 列 Unix 秒 → 可读时间。

        数据行只改第 1 列，其余照抄；升级前先整份复制成 `.bak-<时间戳>.csv`。

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
        if rows[0] not in self._LEGACY_HEADERS:
            return False           # 认不出的表头不动它，避免误改别人的文件
        try:
            with open(backup, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(rows)      # 备份保持原样
        except OSError:
            return False           # 备份写不出来就不动原文件，宁可追加也不冒险
        try:
            with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.HEADERS)
                for row in rows[1:]:      # 老表头丢掉，数据行升级
                    if row:
                        row = list(row)
                        row[0] = _to_time_text(row[0])
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
                "timestamp": format_time(res.timestamp),
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
