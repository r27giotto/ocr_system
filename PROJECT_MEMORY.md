# ocr_system 项目记忆

> **这是本项目的"真相源"。接手前先完整读这里，不要凭代码猜。**
> 最后更新：2026-10-15 23:49 · 对应代码状态：审计问题「一到四」已修复并验证通过
> 内容分两类，请勿混淆：**【已实测】**＝有命令输出为证；**【未验证】**＝只是读代码推断，从没真正跑过。

---

## 1. 这是什么

工业筛选机工位上的**数字识别 + 1/0 判定**程序。一枚圆形标记（药片状）上印有数字（取值 1–48），
系统要识别出它，并判断该数字是否属于预设的目标集合，输出 1 或 0。

单帧链路：

```
取图 → 灰度 → CLAHE 增强 → 定位圆形标记并裁 116×116 ROI
     → 多角度变体（方向分类 + 旋转）→ OCR 识别数字
     → 判定 1/0 → 串口下发 + CSV 记录 + GUI 展示
```

**来源**：本项目是从两个已验证可用的脚本重构而来，它们就在 `test/` 下，是**算法行为的权威依据**：

- `test/test_ocr2.py`（371 行）— 完整可跑的识别脚本，输出 `results.csv`
- `test/test_rename.py` — 调用上面的 `process_image`，按识别结果批量重命名图片

重构原则：**行为必须和 `test/test_ocr2.py` 一致**，只是拆成可复用、可配置、带 GUI 的结构。

---

## 2. 需求与已确定的设计决策

用户侧需求：
- 模型可切换（识别模型多选一）
- 识别角度可勾选（GUI 上多选）
- 图源可切换：文件夹 / 摄像头
- 串口通讯
- 历史记录面板

已确定（**不要擅自推翻**）：

| 决策 | 值 | 出处 |
|---|---|---|
| Qt 绑定 | **PyQt6 6.11.0**（不是 PySide6） | 用户自己的 `pyproject.toml:11` |
| `core/` 分层 | **必须零 Qt 依赖**（纯 Python + cv2 + numpy） | 用户给的目录结构注释「★ 纯 Python，无 Qt 依赖」 |
| 模型加载 | `paddlex.create_model(name)`，按名字缓存 | `core/engine.py` |
| 配置 | 常量**全部**放 `config.yaml`，代码里不硬编码 | `config.yaml` |
| 单一配置文件 | 是，就一个 `config.yaml` | 用户原始要求 |

### ★ 尚未得到用户确认的一点

**串口报文格式**：「字母 + 数字」，如 `D1`/`D0`（判定结果）、`F50`（特征值）。
这是**我提的建议**，用户从头到尾没有明确同意过。实现串口前必须再确认一次。

### 已被砍掉的（scope cuts，别再捡回来）

| 砍掉的东西 | 用户原话 | 出处 |
|---|---|---|
| Arduino 下游动作 | 不管 | m00075 |
| 速度指标 | 「你目前不用管速度」 | m00078 |
| Arduino 串口协议 | 不用考虑 | m00075 |

→ 所以 `config.yaml` 的 `serial:` 段目前**只服务一个简化版串口**，没有握手/应答协议。

---

## 3. 运行环境 【已实测】

| 项 | 值 |
|---|---|
| 解释器 | `E:\Python Project\ocr_system\.venv\Scripts\python.exe` |
| Python | 3.12.10 |
| venv 管理 | **uv**（base 解释器 `E:\Python312`），uv 可执行文件在 `E:\Python313\Scripts\uv.exe` |
| 系统其他解释器 | `E:\Python313\python.exe`（默认）、`E:\Python312\python.exe` |

### ★ 坑：`.venv` 里没有 pip

```
> .venv\Scripts\python.exe -m pip --version
No module named pip        (退出码 1)
```

装包**只能**用 uv：
```powershell
& 'E:\Python313\Scripts\uv.exe' pip install <包名> --python 'E:\Python Project\ocr_system\.venv\Scripts\python.exe'
```

### 已安装版本 【已实测】

```
paddlepaddle       3.3.1        ← 能 import，OK
paddlex            3.4.3
numpy              2.5.4
opencv-python      5.0.0.93
PyQt6              6.11.0
pyserial           3.5
PyYAML             6.0.2
pandas             3.0.6
Pillow             12.3.0
paddleocr          -- 未安装 --   (不需要，我们直接用 paddlex)
```

> 历史备注：早期排查时 `paddlepaddle` **不在** `pyproject.toml` 也不在 venv 里，`import paddle` 直接
> `ModuleNotFoundError`。用户后来在 `pyproject.toml:9` 补了 `"paddlepaddle>=3.3.1"` 并装上了。
> **此问题已消解，不要再当作阻塞项。**

### 依赖的真相在 `pyproject.toml`，不在 `requirements.txt`

**`requirements.txt` 是空文件（0 行）。** 别去改它、也别信它。

`pyproject.toml` 实际声明：
```toml
requires-python = ">=3.12"
dependencies = [
    "numpy>=2.5.4", "opencv-python>=5.0.0.93", "paddlepaddle>=3.3.1",
    "paddlex>=3.4.3", "pyqt6>=6.11.0", "pyserial>=3.5",
]
```

### 模型缓存位置与本地清单 【已实测】

模型根目录：`C:\Users\14734\.paddlex\official_models\`（15 个条目）

`config.yaml` 里列出的模型 vs 本地实际：

| 模型 | 本地存在 | 用途 |
|---|---|---|
| `PP-OCRv6_small_rec` | ✅ | 默认识别模型 |
| `PP-OCRv6_medium_rec` | ✅ | 备选识别模型 |
| `PP-LCNet_x1_0_textline_ori` | ✅ | 默认方向模型 |
| **`PP-OCRv5_server_rec`** | ❌ **本地没有** | `config.yaml:15` 列了它，**选中就需要联网下载** |

→ 想离线跑，只能选 `PP-OCRv6_small_rec` / `PP-OCRv6_medium_rec`。

### 其他

- **不是 git 仓库**（没有版本控制，改动无法回滚，谨慎）
- `logs/` 已存在：`results.csv` 只有 1 行（表头）、`app.log` 空
- `resources/icons/` 存在但**是空的**
- 存在 `.idea/`（PyCharm 工程）

---

## 4. 配置 `config.yaml`（46 行，用户写的）

```yaml
app:        log_dir: "./logs"   csv_output: "./logs/results.csv"   save_csv: true
target:     numbers: ["12","19","20","25","37","41","43"]   valid_min: 1   valid_max: 48
models:     rec_options: [PP-OCRv6_small_rec, PP-OCRv6_medium_rec, PP-OCRv5_server_rec]
            ori_options: [PP-LCNet_x1_0_textline_ori]
            default_rec: PP-OCRv6_small_rec   default_ori: PP-LCNet_x1_0_textline_ori
recognizer: conf_threshold: 0.6   early_exit_conf: 0.98
            angles: [-90,-60,-45,-30,0,30,45,60,90,180]   drop_zero: true
preprocess: roi_size: 116   scale: 1.0   clahe_clip: 2.0   clahe_grid: [8,8]
            min_radius: 20   max_radius: 200
source:     type: "folder"   folder_path: ""   camera_index: 0   fps: 15
            poll_interval_ms: 300   loop: true
serial:     baudrate: 115200   last_port: "COM3"   send_on_change_only: false
```

这些数值全部来自 `test/test_ocr2.py` 的常量，**是调优过的，不要随手改**。

---

## 5. 算法规格（从 `test/test_ocr2.py` 提炼，权威）

### 5.1 定位 ROI

```
gray → cv2.threshold(gray, 127, 255, THRESH_BINARY_INV)
     → 5×5 全 1 核 MORPH_OPEN，再 MORPH_CLOSE
     → findContours(RETR_EXTERNAL, CHAIN_APPROX_SIMPLE) → 取 contourArea 最大者
     → cv2.minEnclosingCircle → (cx, cy, r) 取整
     → 若 r < 20 或 r > 200 → 失败
     → 以 (cx,cy) 为中心取 roi_size(=116) 见方，坐标夹到图像边界
     → 若裁剪后宽或高 < 116 → 失败（贴边的圆会被丢弃）
```

⚠️ **前提：标记是暗的、背景是亮的**（依赖 `THRESH_BINARY_INV`）。
**亮底暗圆**才work；白圆黑底会导致最大轮廓变成整幅背景，半径超 200 而直接失败。
（我第一版合成测试图就是白圆黑底，误判成 bug；换真实样张后通过。）

### 5.2 多角度变体

```
按 |angle| 升序排列（0, ±30, ±45, ±60, ±90, 180）
angle == 0  → 直接用原 ROI，不旋转不缩放
否则        → getRotationMatrix2D((w/2,h/2), angle, scale)
              new_w = int(scale * (h*|sin| + w*|cos|))
              new_h = int(scale * (w*|sin| + h*|cos|))
              M[0,2] += new_w/2 - cx ; M[1,2] += new_h/2 - cy   ← 重新居中
              warpAffine(INTER_LINEAR, BORDER_REPLICATE)
最后：灰度图 → cvtColor(GRAY2BGR)
```

### 5.3 识别与判定

```
对每个变体：
    ori.predict([img]) → parse_ori_output
        若 == 1（倒置）→ cv2.rotate(img, ROTATE_180)
    rec.predict([fixed]) → parse_rec_output → [(text, score)]
    过滤：score < conf_threshold(0.6) 丢弃
          text 只保留数字字符，空了丢弃
          drop_zero 且结果 == "0" 丢弃
    记录候选 (cleaned, score, angle)
    早退：仅当 angle == 0 且 score >= early_exit_conf(0.98) 且数字 ∈ [1,48] → 立即返回
全部候选按 score 降序 → 返回第一个数字 ∈ [valid_min, valid_max] 的
都不满足 → None
```

**注意早退条件绑死了 `angle == 0`** —— 非 0° 角度即使 0.99 也不会早退。

### 5.4 判定 1/0

```
status != "ok" 或 number 为空 或 number == "0"        → 0
int(number) 超出 [valid_min, valid_max]              → 0
number ∈ target_numbers({12,19,20,25,37,41,43})      → 1
否则                                                  → 0
```

→ 即 `output_value == 1` 等价于 `hit == True`。

### 5.5 关键常量（`config.yaml` 里的值都是从这里来的）

```
TARGET_NUMBERS = {12,19,20,25,37,41,43}   CONF_THRESHOLD = 0.6
ROI_SIZE = 116   SCALE = 1.0   EARLY_EXIT_CONF = 0.98   VALID 1..48
ANGLES = (-90,-60,-45,-30,0,30,45,60,90,180)
环境（main.py 也照抄了）：OMP_NUM_THREADS=8, MKL_NUM_THREADS=8, cv2.setNumThreads(1)
demo 用的样张目录：E:\Python Project\project_0\data\test3   （11 张图）
```

---

## 6. 代码现状（逐模块）

`core/` 是干净的纯逻辑层（零 Qt）—— 这是好设计，**别污染它**。

| 文件 | 行数 | 内容 | 状态 |
|---|---|---|---|
| `core/models.py` | 24 | `RecognitionResult` 数据类 | ✅ 完整 |
| `core/parsers.py` | 80 | `parse_rec_output` / `parse_ori_output` | ✅ 完整 |
| `core/preprocess.py` | 83 | `enhance` / `find_roi` / `rotate` / `build_variants` | ✅ 完整，**真实样张 11/11 通过** |
| `core/engine.py` | 31 | `EngineManager`（按名缓存 + `threading.Lock`） | ⚠️ 未跑过 |
| `core/decision.py` | 35 | `DecisionMaker.decide` → 1/0 | ⚠️ 未跑过 |
| `core/recognizer.py` | 96 | `Recognizer.recognize` 多角度循环 + 早退 | ⚠️ 未跑过 |
| `core/pipeline.py` | 57 | `OcrPipeline.run_on_image` 单帧端到端 | ⚠️ 未跑过 |
| `infra/image_source.py` | — | `FolderSource` / `CameraSource` | ⚠️ **依赖 Qt，见缺陷⑥** |
| `infra/serial_service.py` | — | 简化版串口 | ⚠️ 未跑过 |
| `infra/csv_logger.py` | 39 | CSV 记录 | ⚠️ **有截断缺陷，见缺陷①** |
| `app/controller.py` | — | `AppController`（编排层） | ⚠️ 仅构造验证 |
| `app/workers.py` | — | `EngineLoadWorker` / `InferenceWorker`（QThread） | ⚠️ 仅 import 验证 |
| `ui/main_window.py` | — | 主窗口，组装七个面板 | ⚠️ 仅构造验证 |
| `ui/overlay.py` | — | 画框 + 结果叠加 | ⚠️ 仅 import 验证 |
| `ui/widgets/*.py` | — | 七个面板 | ⚠️ 仅 import 验证 |

`core/models.py` 的 `RecognitionResult` 字段（写代码时对齐这个）：
```python
filename: str = ""        number: str = ""          confidence: float = 0.0
angle: int = 0            status: str = "ok"        # ok/no_number/circle_not_found/error
output_value: int = 0     # ★ 决策结果 1/0          hit: bool = False
elapsed_ms: float = 0.0   timestamp: float = field(default_factory=time.time)
roi_box: Optional[Tuple[int,int,int,int]] = None     # x1,y1,x2,y2
frame: Optional[np.ndarray] = None                   # 存整帧，见缺陷⑦
error_msg: str = ""
@property ok -> status == "ok"
```

---

## 7. 缺陷清单

### ✅ 已修复并验证（审计问题「一到四」，用户指令 m00172「先修复一到四」）

| # | 缺陷 | 证据 | 谁修的 |
|---|---|---|---|
| 一 | 4 个模块 import 期 `NameError`（`recognizer.py` 缺 `EngineManager`/`Preprocessor`/`parse_rec_output` 等；`pipeline.py:8-9` 缺三个类），级联炸掉 `app.workers`、`app.controller` | 修前 `FAIL core.recognizer: NameError` | 用户（我并发编辑被 `file changed since it was read` 挡下） |
| 二 | `core/parsers.py:61` 用 `np.asarray` 但没 `import numpy`，而这是**主路径** | 修前 `parse_ori_output({'class_ids':[1]}) -> NameError: name 'np' is not defined`；修后 `→ 1` | 用户 |
| 三 | `core/preprocess.py:24-27` `find_roi()` 和 `:29-32` `rotate()` 是 `...` 空占位 → `find_roi` 永远返回 `None`（所有帧都是 `circle_not_found`），`rotate` 返回 `None` 导致 `build_variants` AttributeError | 修后真实样张 **11/11 找到圆** | 我（逐行照搬 `test_ocr2.py:67-109`） |
| 四 | `ui/main_window.py` 从未 import 七个 widget 类（`ImageView`/`ModelPanel`/`SourcePanel`/`AnglePanel`/`ResultPanel`/`SerialPanel`/`HistoryPanel`），构造即 `NameError` | 修后 `AppController + MainWindow` 构造成功 | 我 |

顺手补的（不在「一到四」内）：`core/recognizer.py:58` 循环体内内联 `import cv2` → 提到文件顶部。

**验证证据（全部实测）**：
```
compileall                              exit 0
import 21 个模块                         21/21 OK
find_roi 真实样张 project_0\data\test3   11/11 找到圆
find_roi 12.png (926×1082)              半径 106，ROI 116×116  ✓
build_variants 六角度尺寸                 0°→116², ±30°→158², ±90°→116², 180°→116²  ✓
AppController + MainWindow(真配置)        构造成功，标题 "OCR 识别系统 v2.0"
  面板: [ModelPanel, SourcePanel, AnglePanel, ResultPanel, SerialPanel, HistoryPanel, ImageView]
```

### ⚠️ 待修（**用户尚未要求修**，但会咬人）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| ① | `infra/csv_logger.py:16` | `open(self.path, "w", ...)` —— **每次启动清空 `logs/results.csv`** | 改 `"a"`，或按 `app.save_csv` 决定 |
| ② | `main.py:32` + `ui/main_window.py:150` | 两边都连/调 `controller.shutdown()` → **关闭时执行两次** | 只保留一处 |
| ③ | `config.yaml:8-9` 与 `:22-25` | `valid_min`/`valid_max` 在 `target:` 和 `recognizer:` **重复定义**，会漂移 | 收敛到一处 |
| ④ | `config.yaml:35-41` | `source:` 段**根本没被读取**；`SourcePanel` 里硬编码 15fps / 300ms / loop | 接线到 config |
| ⑤ | `config.yaml:44-45` | `serial.last_port` / `baudrate` 未被使用 | 接线到 `SerialPanel` |
| ⑥ | `infra/image_source.py:3` | `from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal` → **`infra/` 不是纯 Python 层**。`core/` 是干净的 | 至少知情；要么下沉到 app/ui，要么接受 |
| ⑦ | `core/models.py:19` + `ui/widgets/history_panel.py:66` | `frame` 存**整帧**，`MAX_ITEMS = 200` → 最多 **200 张整帧常驻内存** | 存缩略图 |
| ⑧ | `core/pipeline.py:45` | 调 `decider.decide(num)` 没传 `status`，而 `decision.py:23` 有这个参数（默认 `"ok"`）→ 参数形同虚设 | 传 `res.status` |

---

## 8. ★ 当前唯一阻塞项：模型目录被 OS 权限挡住

**这挡死了端到端运行**，`EngineManager.get_rec/get_ori` 一旦 `create_model()` 就会抛异常。

【已实测】故障表现：
```
os.listdir(r'C:\Users\14734\.paddlex\official_models\PP-LCNet_x1_0_textline_ori')
  → PermissionError [WinError 5] 拒绝访问
os.listdir(r'C:\Users\14734\.paddlex\official_models\PP-OCRv6_small_rec')
  → PermissionError [WinError 5] 拒绝访问
```
- `open('...\PP-LCNet_x1_0_textline_ori\inference.yml')` → `PermissionError [Errno 13]`
- 但 `os.path.exists()` 对同一路径返回 **False**（stat 被静默拒绝）
- **对照组**：`...\PP-LCNet_x1_0_doc_ori\.gitattributes` 可正常读取

**诊断结论**：这是 **Windows 文件系统 ACL 问题（OS 级 `WinError 5`）**，
**不是 DSH 沙箱限制**（沙箱会打印 `[sandbox: file access denied under workspace-write mode]`，此处没有）。
只有这两个子目录被拒，同级的 `PP-LCNet_x1_0_doc_ori` 却正常 —— 典型的目录 ACL 损坏。

**修复办法**（技能 `diagnose-windows-sandbox-acl`，一条命令诊断+修复，**须批准非受限执行**）：
```powershell
& '<skill目录>\scripts\diagnose-windows-sandbox-acl.ps1' `
  -Path 'C:\Users\14734\.paddlex\official_models\PP-LCNet_x1_0_textline_ori' `
  -AllowRoot 'C:\Users\14734\.paddlex\official_models' `
  -Out '<持久且属于用户的目录>'
exit $LASTEXITCODE
```
一次只传一个路径，两个坏目录要跑两次。`-Out` 要选持久目录（**不能**用技能资源目录，它卸载即删）。
**修完后必须再受限地重跑原失败操作**验证。

---

## 9. 【未验证】的部分 —— 别当成已完成

以下**只在 import / 构造层面验证过，从未真正执行**（因为一执行就要加载模型，卡在第 8 节）：

- `EngineManager` 的模型缓存是否真的只加载一次
- `Recognizer.recognize` 的角度循环、方向分类转 180°、早退逻辑是否正确
- `DecisionMaker.decide` 的 1/0 判定
- `OcrPipeline.run_on_image` 的端到端结果
- 所有 `infra/` 串口、图源、CSV 的实际读写
- 全部 GUI 交互（只验证了「能构造出来」，没点过任何按钮）
- `test/test_rename.py` 的重命名行为

**所以：「一到四已修复」可以担保；「整条链路正确」不能担保。**

---

## 10. 下一步

1. **修第 8 节的模型目录权限** → 然后跑通单帧端到端，才能验证第 9 节的算法（**优先级最高**）
2. 再决定要不要清掉第 7 节的 ①–⑧ 待修缺陷
3. `/brainstorming` 的设计文档**始终没写**（用户 m00043 发起）—— 系统已经写出来了，文档还欠着
4. 串口报文格式仍需用户拍板（见第 2 节）

---

## 11. 常用命令

```powershell
# 解释器（.venv 里没有 pip，装包用 uv）
$py = 'E:\Python Project\ocr_system\.venv\Scripts\python.exe'
$env:PYTHONPATH = 'E:\Python Project\ocr_system'

# 语法检查（全部模块）
& $py -m compileall -q core infra app ui main.py ; "exit=$LASTEXITCODE"

# 启动 GUI —— 必须在项目根目录！main.py:18 用相对路径读 config.yaml
Set-Location 'E:\Python Project\ocr_system'
& $py main.py

# 装包
& 'E:\Python313\Scripts\uv.exe' pip install <包名> --python $py

# 让 PaddleX 跳过联网检查（离线/无网时有用）
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
```

**若要在无显示器环境构造 GUI**：加 `$env:QT_QPA_PLATFORM = 'offscreen'`。
此时会打印 `QFontDatabase: Cannot find font directory` —— 那是 offscreen 专有告警
（Qt 6 起不再随包发字体），真实 Windows GUI 用系统字体，**无影响，不要当 bug 修**。

---

## 12. 时间线

| ref | 事件 |
|---|---|
| m00001 | 用户给出目录结构，要求建文件/文件夹 |
| — | 骨架建成（31 文件 / 7 目录，docstring + TODO）；期间修复过一次 Windows ACL 问题才能写入 |
| m00043 | 用户发起 `/brainstorming`，转入设计讨论 |
| — | 确认需求、砍掉 Arduino 与速度指标、审计全代码，列出问题一到五 |
| m00170 | 我问「先修一到四，还是先接着聊设计」 |
| m00172 | 用户：「先修复一到四」 |
| — | 一到四 + 一处 import 卫生修复完成，全部实测通过 |
| m00228 | 用户：「你先生成一个存放记忆的md文件在项目目录下」→ **本文件** |
