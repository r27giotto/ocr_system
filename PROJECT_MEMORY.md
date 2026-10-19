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

### ✅ 串口报文格式：已由 Arduino 固件定案（m03236）

原「尚未确认」的那一条**已经不用再问了**。用户在
`E:\Python Project\ocr_system\arduino\sketch_oct19a\sketch_oct19a.ino` 里写出了接收端，
它认的就是**裸字符 `'1'` / `'0'`**：

| 收到 | 固件动作 |
|---|---|
| `'1'` | `digitalWrite(VALVE_PIN=8, HIGH)` 开**喷气阀** → 非阻塞计时 `PULSE_MS = 100` ms 后自动关阀；`LED_PIN=13` 跟随脉冲 |
| `'0'` | 立即关阀（注释：急停/复位用），不吹气 |
| 其它 | 忽略 |

`Serial.begin(115200)` 与 Python 侧一致。→ 我此前建议的「字母+数字」(`D1`/`D0`/`F50`)
**作废**，实现里的裸字符才是对的。

**语义确证**：`'1'` 接喷气阀 → `1` = **NG = 吹掉不良品**，`0` = G = 放行。
这用硬件确认了 §5.4 / §6.3 里原先只是【推断】的「`TARGET_NUMBERS` 是不良品编号」。

⚠️ **因此，如果哪天要「连续两颗 NG 都吹」，`serial.send_on_change_only` 必须保持
`false`** —— 勾成 true 后值不变就不发，固件收不到第二个 `'1'`，第二颗就不吹。
（m03412 起这个选项**已被删除**，见 §6.4 —— 现在就是每帧必发。）

### ✅ 设计问答 Q1–Q6 已全部裁定（m03646）

用户在 m03646 一次性回了四个问题（原话照录）：

| 问题 | 用户回答 | 落到代码/文档上的结论 |
|---|---|---|
| **Q1** 识别失败时串口发什么 | 「识别失败时串口发0」 | 选项 (a)，**当前实现即正确，不改代码**。这是**明示接受的取舍**：读不出来的缺陷件会被放行到下游。界面仍用 `?` 区分「没判出来」和「良品」，线上字节不区分。缺陷 D1 关闭为「按用户裁定执行」 |
| **Q2** 一帧里有几颗标记 | 「每一帧只会出现一颗」 | **一个结果对应一颗标记**，`RecognitionResult` 单结果结构成立，不需要多结果。<br>未明确的一半：是否可能**亮底暗字** —— 当前 `find_roi` 用 `THRESH_BINARY_INV`（只认暗标记/亮底，§5.1），按现状实现 |
| **Q4** 离线是不是硬约束 | 「最好是离线」 | **偏好而非硬约束**。现状已满足：模型全在 `models/official_models/`、依赖固化，断网可跑。`PP-OCRv5_server_rec` 本地缺失、选中会联网，`config.yaml` 里已加注释警示。今后加依赖/换模型**先问** |
| **Q6** COM 口接的是什么 | 「COM口连接的时arduino uno r3」 | 目标板 = **Arduino Uno R3**（ATmega328P @16 MHz / 2 KB RAM，ATmega16U2 转 USB CDC）。115200 与固件一致。⚠️ **打开串口会因 DTR 拉低导致板子复位，bootloader 约 1.5~2 s，这段收到的字节被丢弃** → `SerialService.open()` 不等待，**打开后立刻跑图时第一颗的判定可能丢掉**，待真机确认（见 §9 下一步） |

→ **至此设计文档 §12 无待决项**。原本 Q3（字节格式）由固件定案、Q5（丢不丢帧）由
m03412 裁定、Q1/Q2/Q4/Q6 由 m03646 裁定。

### 已被砍掉的（scope cuts，别再捡回来）

| 砍掉的东西 | 用户原话 | 出处 |
|---|---|---|
| Arduino 下游动作 | 不管 | m00075 |
| 速度指标 | 「你目前不用管速度」 | m00078 |
| Arduino 串口协议 | 不用考虑 | m00075 |

→ 前两条仍有效（Python 侧不实现下游逻辑、不追速度）。第三条**已由用户自己补上**：
他写了固件并（m03236）要求把 `arduino/` 一起提交，所以协议不再是「不用考虑」，
而是「已由固件确定、Python 侧照着发裸字节」。`config.yaml` 的 `serial:` 段仍只服务
这个简化版串口，没有握手/应答。

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
paddlepaddle            3.3.1        ← 能 import，OK
paddlex                 3.7.2        ← 必须 >=3.7.2，见第 8 节
numpy                   2.3.5        ← paddlex 3.7.2 要求 numpy<2.4
opencv-contrib-python   5.0.0.93     ← 必须是 contrib 版，见第 8 节
pypdfium2               5.14.0
python-bidi             0.6.11
PyQt6                   6.11.0
pyserial                3.5
PyYAML                  6.0.2
pandas                  3.0.6
Pillow                  12.3.0
paddleocr               -- 未安装 --   (不需要，我们直接用 paddlex)
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
    "numpy>=2.3.5",                      # 不能写 >=2.5.4：paddlex 3.7.2 要求 numpy<2.4
    "opencv-contrib-python>=5.0.0.93",   # 不是 opencv-python，见第 8 节
    "paddlepaddle>=3.3.1",
    "paddlex>=3.7.2",                    # 3.4.3 的注册表里没有 PP-OCRv6_*
    "pypdfium2>=5.14.0",                 # paddlex 只在 extras 里声明，裸装必缺
    "python-bidi>=0.6.11",               # 同上
    "pyqt6>=6.11.0",
    "pyserial>=3.5",
]
```

### 模型缓存位置与本地清单 【已实测】

**模型已经搬进项目内**：`E:\Python Project\ocr_system\models\official_models\`（15 个目录，477.1 MB）。

做法是 `main.py` / `test/run_app.py` 在**任何 paddlex import 之前**设：
```python
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", "<项目根>/models")
```
依据：`paddlex/utils/cache.py:29` `CACHE_DIR = os.environ.get("PADDLE_PDX_CACHE_HOME", ~/.paddlex)`
（**import 时求值**，晚了就无效），模型目录拼法是
`official_models.py:880` `_save_dir = Path(CACHE_DIR) / "official_models"`，
再在 `:942` `self._save_dir / f"{candidate_name}"` 找目录；找到就用，找不到才下载。

另一条路是给 `create_model(name, model_dir=...)` 直接传本地目录
（`paddlex/inference/models/__init__.py:92 _resolve_model_dir`），但那样要逐个改 `EngineManager`，
且丢失「缺失自动下载」的能力，**所以没采用**。

`config.yaml` 里列出的模型 vs 本地实际：

| 模型 | 本地存在 | 用途 |
|---|---|---|
| `PP-OCRv6_small_rec` | ✅ 20.5 MB | 默认识别模型 |
| `PP-OCRv6_medium_rec` | ✅ 73.3 MB | 备选识别模型 |
| `PP-LCNet_x1_0_textline_ori` | ✅ 6.5 MB | 默认方向模型 |
| **`PP-OCRv5_server_rec`** | ❌ **本地没有** | `config.yaml:15` 列了它，**选中就需要联网下载**（现在会下到项目内 `models/`） |

→ 想完全离线跑，只能选 `PP-OCRv6_small_rec` / `PP-OCRv6_medium_rec`。

⚠️ 副作用要记住：设了 `PADDLE_PDX_CACHE_HOME` 之后 **`~/.paddlex` 不再被读取**。
要加新模型，要么联网让它下到 `models/`，要么手动从 `~/.paddlex` 复制过来。
`models/` 已在 `.gitignore` 里（477 MB 的产物不入库）。

### 其他

- **已是 git 仓库**（分支 `main`；初始化与提交见第 12 节时间线；**无 remote**）
- `logs/` 已存在：`results.csv` 只有 1 行（表头）、`app.log` 空
- `resources/icons/` 存在但**是空的**
- 存在 `.idea/`（PyCharm 工程）
- `arduino/` 是**用户自己写的 Arduino 接收端固件**（m03236，独立于 Python 工程）：
  `arduino/sketch_oct19a/sketch_oct19a.ino`（43 行）—— 收 `'1'` 开喷气阀 100 ms、
  收 `'0'` 立即关，`Serial.begin(115200)`。协议语义见 §2「串口报文格式」

---

## 4. 配置 `config.yaml`（46 行，用户写的）

```yaml
app:        log_dir: "./logs"   csv_output: "./logs/results.csv"   save_csv: true
target:     numbers: ["12","19","20","25","37","41","43"]   valid_min: 1   valid_max: 48
models:     rec_options: [PP-OCRv6_small_rec, PP-OCRv6_medium_rec, PP-OCRv5_server_rec]
            ori_options: [PP-LCNet_x1_0_textline_ori]
            default_rec: PP-OCRv6_small_rec   default_ori: PP-LCNet_x1_0_textline_ori
recognizer: conf_threshold: 0.5   debug_aggregate: true
            early_exit_conf: 0.98 ← 【已废弃，不再被读取】
            angles: [-90,-60,-30,0,30,60,90,180]   drop_zero: true
preprocess: roi_size: 116   scale: 1.0   clahe_clip: 2.0   clahe_grid: [8,8]
            min_radius: 20   max_radius: 200
source:     type: "folder"   folder_path: ""   camera_index: 0   fps: 15
            poll_interval_ms: 300   loop: false
serial:     baudrate: 115200   last_port: "COM3"   send_on_change_only: false
```

这些数值全部来自 `test/test_ocr2.py` 的常量，**是调优过的，不要随手改**。

> **`source:` 段是例外**：它不来自 test_ocr2.py，而是**输入源面板的初始值**。
> `MainWindow` 把 `config["source"]` 传给 `SourcePanel(config)`，面板据此决定
> 打开界面时选哪个 radio、路径框内容、`fps` / `interval_ms` / `loop` 的初值
> （缺键时兜底 `folder` / 15 / 300 / **false**）。界面上改了**不会写回**
> `config.yaml`。`loop` 默认 **false（不勾选）**——`FolderSource` 放完一遍就
> `finished`；勾上才从头再来。

> 角度面板分**两组**（`ui/widgets/angle_panel.py`）：
>
> | 组 | 角度 | 受「负号」影响 |
> |---|---|---|
> | **固定角度**（单独一行） | `0°`、`180°` | **否** —— `-0°` 就是 `0°`，`-180°` 与 `180°` 是同一次旋转，没有正负之分 |
> | **旋转角度**（5 列网格，范围随步长） | 默认 `5°`~`175°` 每 `5°` 一个，共 35 个 | 是 —— 勾上「负号」时每个勾选角度连带尝试 `-θ` |
>
> 旋转角度的**步长由下拉框选**：`5 / 10 / 15 / 20 / 30` 度，也就是把 180° 分成
> `36 / 18 / 12 / 9 / 6` 等分。网格恒为 `range(step, 180, step)`，所以各步长下
> 旋转格数依次是 **35 / 17 / 11 / 8 / 5**，复选框总数（含固定行 2 个）
> **37 / 19 / 13 / 10 / 7**。切换步长时，仍在新网格上的勾选**保留**，掉出网格的
> 被取消并打印一行提示；「默认」按钮只复位勾选与负号，**不动步长**。
>
> `config.yaml` 里那一行是**初始状态**：取 `|a|` 分到两组，
> 出现过负数就把「负号」默认勾上。所以
> `[-90,-60,-30,0,30,60,90,180]` ≡ 勾 `0°/180°` + 勾 `30°/60°/90°` + 负号
> → 展开 `[0, -30, 30, -60, 60, -90, 90, 180]`（与旧版默认完全一致）。
> 不在网格上的（非 `5` 的整数倍）会被丢弃并打印一行提示。
>
> 因为旋转网格里没有 `0`/`180`，展开时 `-a` 永远不会撞上固定角度，
> **`selected_angles()` 里不需要任何特例**——这是把两组拆开的额外好处。
>
> （用户指令：m00749「每个10度都有」→ m00913「添加负号勾选，只显示 0-180，步长 10」
> → m01073「0度和180度独立出来不受负号影响，因为 -0度 -180度没意义」
> → m01529「面板上10-170增加到5-175，步长为5，然后添加一个下拉选项，
> 可以勾选步长为5,10,15,20,30」）

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
对每个变体（跑完全部角度，不早退）：
    ori.predict([img]) → parse_ori_output
        若 == 1（倒置）→ cv2.rotate(img, ROTATE_180)
    rec.predict([fixed]) → parse_rec_output → [(text, score)]
    过滤：score < conf_threshold(0.5) 丢弃          ← 只做「准入」
          text 只保留数字字符，空了丢弃
          drop_zero 且结果 == "0" 丢弃
    记录候选 (cleaned, score, angle)

跑完全部角度后，按数字分组聚合（_aggregate_by_number）：
    每个数字 → agg = Σ(score - conf_threshold)，取 6 位小数
               max = 最高单次分, votes = 票数
    按 (agg, max, votes) 三元组降序排
取第一个数字 ∈ [valid_min, valid_max] 的；
返回它在所有票里置信度最高的那次 (num, score, angle)
都不满足 → None
```

**★ 聚合分为什么是 `Σ(score - conf_threshold)` 而不是 `Σscore`**：
`Σscore` 奖励的是**票数**，不看票的强弱 —— 于是「3 张勉强及格的弱票」会压过
「2 张 0.9997 的强票」。这在真实数据上翻过车（见 §5.3.1）。
减去准入门槛的效果是：**每张票只按「高出噪声底的部分」计入证据**，
弱票几乎不贡献，强票贡献很多；同时**仍然保留「多角度互证」的性质** ——
两张 0.8 的票（边际 0.3+0.3=0.6）依然胜过一次 0.9 的票（边际 0.4）。

**★ 早退已删除（2026-10-16）**：旧版「`angle == 0` 且 score ≥ 0.98 就立即返回」
已被移除 —— 聚合分靠各角度的票累加，早退等于放弃后面的票，聚合就失去意义。
代价是每帧都要跑满全部角度（速度已明确不在本项目范围内）。

**平局规则**：聚合分相同 → 比最高单次分；再相同 → 比票数。
聚合分**四舍五入到 6 位**再比较：否则 `0.9+0.9-1.0` 与 `0.9+0.7+0.7-1.5`
（本是同一个数）会因 1e-16 的浮点尾差抢先决定，把「比票数」这一级架空。
`best_angle` 取该数字所有票里置信度最高的那一次的角度（并列时取先遇到的，
即 `|angle|` 更小的）。

真实数据佐证（`_verify_margin.py`，阈值 0.5，默认 8 个角度）：
`project_0\data\test3\12.png` → `12` 拿 3 票胜出 → `('12', 0.9995, 0°)`；
`37.png` → `37` **只有 -30° 这一票**（0.9788）仍然胜出 → `('37', 0.9788, -30°)`。

### ✅ 5.3.1 已修复：`Σscore` 曾把 `20.png` 判成 `2`（**留档，别再犯**）

用户最初的规则是 `agg = Σscore`，端到端实测时 `project_0\data\test3\20.png`
被判成 **`2`**，而 demo（`test_ocr2.py`）读作 **`20`**，文件名本身就是当年按
`20` 重命名的 —— 即**这是聚合规则引入的真实回归**。逐角度原始票：

| 角度 | ori | 模型原样输出 | 分数 | 是否进池 |
|---|---|---|---|---|
| 0° | 0 | `'2'` | 0.7407 | 进 |
| -30° | 0 | `'6'` | 0.1217 | 弃 |
| 30° | 0 | `'2'` | 0.7465 | 进 |
| -60° | 0 | `'00'` | 0.4035 | 弃 |
| 60° | 1 | `'00'` | 0.5312 | 进 |
| **-90°** | 1 | **`'20'`** | **0.9997** | 进 |
| **90°** | 1 | **`'20'`** | **0.9993** | 进 |
| 180° | 1 | `'2'` | 0.5999 | 进 |

聚合结果（旧规则）：`2 → sum=2.0871 votes=3` **>** `20 → sum=1.9990 votes=2` → 返回 `2`。

**根因**：`agg = Σscore` 奖励的是**票数**，不区分票的强弱。
三张 0.60~0.75 的**弱票**（都出现在零件并非正立的角度）合起来压过了两张 0.9997 的**强票**。
即：**「很多次勉强认出」会赢过「两次几乎确定」** —— 这正是聚合分想解决的问题的反面。

**采纳的修法（用户 m01818「按照修法1修改」）：边际分求和**
`agg = Σ(score - conf_threshold)` —— 只有高出噪声底的部分算证据。
上例：`2 → 0.5871` vs `20 → 0.9990` → **`20` 胜**（实测 `20.png → 20 conf=0.9997 angle=-90°`）。
既保留「多角度互证」，又让弱票几乎不贡献。

当时评估过但**未采纳**的两条，留档备查：
- 最高分优先、聚合分次之（排序键改 `(max, agg, votes)`）→ `20` 胜，但基本退回旧规则。
- 只让高分票进池（把 `conf_threshold` 提到 0.9）→ `20` 胜，但会牺牲
  「只在某个角度勉强认出」的正确结果（`37.png` 只有一票 0.9788）。
注意**准入门槛本身没有提高**：仍是 0.5，弱票照样进池参与投票，只是权重变小。

### 5.4 判定 1/0

```
status != "ok" 或 number 为空 或 number == "0"        → 0
int(number) 超出 [valid_min, valid_max]              → 0
number ∈ target_numbers({12,19,20,25,37,41,43})      → 1
否则                                                  → 0
```

→ 即 `output_value == 1` 等价于 `hit == True`。

**语义已由固件确认（m03236）**：`1` = **NG = 吹掉不良品**（Arduino 把 `'1'` 接到喷气阀），
`0` = G = 放行。所以 `TARGET_NUMBERS` 是**不良品编号**，不是良品编号。

### 5.4.1 串口输出与 Arduino 接收端（m03236）

Python 侧（`infra/serial_service.py` 的 `send_value`）只发**裸单字节**：
`output_value == 1` → `b'1'`，否则 → `b'0'`。波特率 `115200`（与固件一致），
`bytesize=8 / parity=N / stopbits=1 / timeout=0.05 / write_timeout=0.2`。

接收端 `E:\Python Project\ocr_system\arduino\sketch_oct19a\sketch_oct19a.ino`（43 行，用户写的）：

```cpp
const int VALVE_PIN = 8;        // 驱动 MOSFET 栅极（经光耦）
const int LED_PIN   = 13;       // 板载指示灯，跟随脉冲
const unsigned long PULSE_MS = 100;   // ⚠️ 必须按喷气嘴规格调（典型电磁阀 10~50ms）

Serial.begin(115200);
loop():
  收 '1' → VALVE 拉高 + 记 pulseStart，pulsing=true
  收 '0' → VALVE 拉低，pulsing=false          // 急停/复位
  其它   → 忽略
  到 PULSE_MS 且 pulsing → VALVE 自动拉低     // 非阻塞，不 delay()
```

要点：
- **`'0'` 不吹气**，只是「确保阀关着」，所以识别失败发 `'0'` ＝ **放行这颗**
- `PULSE_MS = 100` 是**吹气时长**，不是产线节拍；太短阀打不开、太长浪费气且发热
- ⚠️ 固件对**每个收到的 `'1'`** 吹一次。`send_on_change_only` 曾能破坏这一点，
  **m03412 起该选项已删除**（见 §6.4），现在每帧必发
- 固件**没有**收「频率」的代码；早期方案里的 `F50` 之类频率报文从未实现，也别再加

#### ⚠️ `'0'` 是「立刻关阀」，不是空操作 —— 会掐断上一颗的脉冲

这一条是把固件和「每帧必发一个字节」放在一起看才暴露的：

```
第 N 颗是 NG  → 发 '1' → 阀开，pulseStart 开始计时 100ms
第 N+1 颗是 G → 发 '0' → 固件立刻 digitalWrite(LOW) 并把 pulsing 清 false
```

**如果第 N+1 个字节在 100ms 之内到达，第 N 颗的吹气会被提前截断**，实际吹气时长
= 两帧的间隔，而不是 `PULSE_MS`。

- 现在**不会**触发：单帧约 220ms > `PULSE_MS = 100`，脉冲先自然结束
- 但这是**隐式耦合**：一旦识别变快（换小模型 / 少勾角度 / 相机 fps 提高）导致帧间隔
  < 100ms，NG 的吹气就会被后继的 G 截短
- 要彻底解耦，两条路：**(a)** Python 侧只在 `'1'` 时不发后继的 `'0'`（但那样就破坏
  「每帧必发」）；**(b)** 固件把 `'0'` 处理改成「不打断正在进行的脉冲」
  （`if (!pulsing) { 关阀 }`）。**这是固件的语义选择，不是 Python 侧能单方面定的**

#### 接收端板子：**Arduino Uno R3**（m03646 确认，m03767 已烧录验证）

| 项 | 值 / 影响 |
|---|---|
| 板子 | **Arduino Uno R3**：ATmega328P @16 MHz，2 KB RAM，经 **ATmega16U2** 转 USB CDC |
| 能力 | 固件几十行、单字节协议，资源绰绰有余；`Serial.begin(115200)` 与 Python 侧一致 |
| COM 口号 | 随插拔变化 → UI 必须有「刷新端口」；`serial.last_port` 仍未接线（缺陷 D3 另一半） |
| ✅ **烧录状态** | **已烧录，行为符合预期**（用户 m03767 确认：`'1'` 触发、`'0'` 关闭、100ms 自动收） |
| ✅ **Python 侧已驱动成功** | **m03833：跑 `test/run_app.py` 发图后，NG 帧 Arduino 板载 LED 亮** → **整条链路打通**：图像 → OCR → G/NG → `SerialService` → COM 口 → 固件 `'1'` 分支 → `VALVE_PIN`/`LED_PIN` 拉高。波特率 115200、端口打开、字节编码全部实测正确。<br>⚠️ 只观察到 **LED**（`LED_PIN = 13`，与 `VALVE_PIN` 同一分支）。**气动阀是否真的吹出气、吹得动那颗料，尚未验证**（需接阀 + 气源） |
| ⚠️ **DTR 自动复位** | 理论上打开端口会拉低 DTR → 板子重启，bootloader 约 1.5~2 s 内的字节被丢弃。**m03833 实测：不影响整体流程**（跑图后 NG 正常亮灯）。但「**打开串口后的第一颗判定是否被吞掉**」仍未单独验证 —— 要确认得数「界面已处理 N」与「板子亮灯次数」是否相等 |

### 5.5 关键常量（`config.yaml` 里的值都是从这里来的）

```
TARGET_NUMBERS = {12,19,20,25,37,41,43}   CONF_THRESHOLD = 0.5（2026-10-16 由 0.6 下调）
ROI_SIZE = 116   SCALE = 1.0   VALID 1..48
EARLY_EXIT_CONF = 0.98  ← 【已废弃】早退已删除，config 里的这个键不再被读取
ANGLES = (-90,-60,-45,-30,0,30,45,60,90,180)  ← demo 的；本项目面板默认 (-90,-60,-30,0,30,60,90,180)
环境（main.py 也照抄了）：OMP_NUM_THREADS=8, MKL_NUM_THREADS=8, cv2.setNumThreads(1)
demo 用的样张目录：E:\Python Project\project_0\data\test3   （11 张图）
```

---

## 6. 代码现状（逐模块）

`core/` 是干净的纯逻辑层（零 Qt）—— 这是好设计，**别污染它**。

| 文件 | 行数 | 内容 | 状态 |
|---|---|---|---|
| `core/models.py` | 40 | `RecognitionResult` 数据类 + `ok` / **`output_text`（判定显示 G/NG/? 的唯一真源，见 §6.3）** | ✅ 完整 |
| `core/parsers.py` | 80 | `parse_rec_output` / `parse_ori_output` | ✅ 完整 |
| `core/preprocess.py` | 83 | `enhance` / `find_roi` / `rotate` / `build_variants` | ✅ 完整，**真实样张 11/11 通过** |
| `core/engine.py` | 31 | `EngineManager`（按名缓存 + `threading.Lock`） | ⚠️ 未跑过 |
| `core/decision.py` | 35 | `DecisionMaker.decide` → 1/0 | ⚠️ 未跑过 |
| `core/recognizer.py` | 145 | `Recognizer.recognize` 多角度循环 + **`_aggregate_by_number` 按数字聚合分选结果**（无早退） | ✅ 已实测（真实样张，见 §5.3） |
| `core/pipeline.py` | 57 | `OcrPipeline.run_on_image` 单帧端到端 | ✅ 已实测（真实模型 + 12 张真实样张，11/12 ok） |
| `infra/image_source.py` | 146 | `FolderSource`（single-shot 定时器，一帧在飞）/ `CameraSource`（`threading.Event` 等 ack）；`read_failed` 上报坏图 | ✅ 已实测（见 §6.4） |
| `infra/serial_service.py` | 67 | 简化版串口；发裸 `b'1'`/`b'0'`（协议已由固件定案，见 §5.4.1） | ⚠️ 未接过真设备 |
| `arduino/sketch_oct19a/sketch_oct19a.ino` | 43 | **用户写的**接收端固件：`'1'`→开阀 100ms→自动关，`'0'`→立即关 | ✅ **已烧录，行为符合预期**（m03767）；⚠️ 未与 Python 侧联调 |
| `infra/csv_logger.py` | 39 | CSV 记录 | ⚠️ **有截断缺陷，见缺陷①** |
| `app/controller.py` | 163 | `AppController`（编排层）；**每帧必发一个串口字节**，`frames_in`/`results_out` 对账 | ✅ 已实测（见 §6.4） |
| `app/workers.py` | 79 | `EngineLoadWorker` / `InferenceWorker`；**队列不丢帧**，`frame_processed` 做背压 | ✅ 已实测（见 §6.4） |
| `ui/main_window.py` | 181 | 主窗口，组装七个面板；竖直 `QSplitter` 分隔历史区，右列包 `QScrollArea`；状态栏显示 `→ G/NG` 与 `待处理 N` | ✅ 已实测（见 §6.1 / §6.3 / §6.4） |
| `ui/overlay.py` | 36 | 画框 + 结果叠加；**大号 `G`/`NG` 按文字宽度右对齐**，配色同 §6.3 | ✅ 已实测（见 §6.3） |
| `ui/widgets/angle_panel.py` | 263 | 固定角度 0°/180° 单独一行（不受负号影响）+ 旋转角度网格（**步长下拉框 5/10/15/20/30**，默认 5° 共 35 格）+「负号」开关 + 全选/仅 0°/反选/默认 | ✅ 已实测 |
| `ui/widgets/history_panel.py` | 187 | 历史缩略图，**固定 120×120** + 高度可一直往下拖（最小 113px）+ 横/竖滚轴按需 + 清除按钮；卡片显示 `数字 → G/NG/?`，边框色同 §6.3 | ✅ 已实测（见 §6.2 / §6.3） |
| `ui/widgets/result_panel.py` | 65 | 结果显示；**大方框显示 `G`/`NG`/`?`**（底色绿/红/橙），tooltip 给出原始 `output_value` | ✅ 已实测（见 §6.3） |
| `ui/widgets/*.py`（其余四个） | — | 模型/源/串口/图像面板 | ⚠️ 仅 import 验证 |

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

### 6.1 界面布局（m00749 改动后，已实测）

```
QVBoxLayout(centralWidget) 实际上已被替换为：
  v_splitter (竖直 QSplitter)
  ├── splitter (横向 QSplitter, 3:1)
  │   ├── ImageView
  │   └── right_scroll (QScrollArea)
  │       └── right QWidget：ModelPanel + SourcePanel + AnglePanel
  │                          + ResultPanel + SerialPanel + addStretch
  └── HistoryPanel          ← 拖动这个分隔条即可动态调节历史区高度
```

- 历史缩略图是**固定尺寸**（m01143 改动）：`HistoryItem.THUMB_W = THUMB_H = 120`，
  卡片宽 `ITEM_W = THUMB_W + 12 = 132`，整个卡片 `setFixedSize` + 固定尺寸策略。
  缩略图用 `np.zeros((120,120,3))` 黑底 + 等比缩放居中贴图（不是拉伸，所以会有黑边，属正常）。
  **拉高历史区只会露出更多滚动区，不会放大图片**——这条是 m01143 用户明确要求的。
- 「清除历史」按钮 → `HistoryPanel.clear()` + 发 `cleared` 信号 →
  `MainWindow._on_history_cleared()` 把状态栏统计一并归零。
- ⚠️ **布局陷阱（踩过一次）**：右侧那列面板的总最小高度（实测 **939px**，其中角度面板
  37 格时 236px → 19 格时 167px → 拆出固定角度行后 188px → 步长改 5° 共 37 格后 250px）会超过默认给它的 643px，竖直分割器宁可
  把空间全给右列、把历史区钳在最小 120px 且**拖不动**（`setSizes` 被最小高度钳住）。
  修法是把右列包进 `QScrollArea`，且**必须**把它的最小宽度显式设为
  `right.minimumSizeHint().width() + 竖向滚动条宽度`——`QScrollArea` 自己算的最小宽度
  不含内部控件的要求，否则外侧会把右列压窄到内容以下、把控件裁掉。
  结论：右列比视口高是**常态**，它自己出竖向滚动条，不影响历史区。
- ⚠️ **反向陷阱（踩过两次）**：
  1. m01143 之前把缩略图尺寸绑到历史区高度 ⇒ 拉高历史区图片跟着变大（用户不接受）。
     结论：**区域可调，图片固定**，两者必须分开。
  2. m01143 修完把 `scroll.setMinimumHeight(THUMB_H + 44 = 164)` 当最小值 ⇒
     面板 `minimumSizeHint` 高被顶到 221，分割条**往下拖不动**（用户 m01221 报的问题）。
     修法：面板最小值放开到 `HistoryPanel.MIN_VIEW_H = 56`（面板实测最小 113px），
     同时把 `setVerticalScrollBarPolicy` 从 `ScrollBarAlwaysOff` 改成 `ScrollBarAsNeeded`
     ——矮了缩略图会被裁切，**靠竖向滚轴看全**；横向滚轴照旧按需出现。
     `main_window` 的 `setSizes([640, 230])` 初值不变（230 能完整显示一行）。

### 6.2 历史缩略图尺寸与历史区高度（m01143 + m01221，已实测）

| 历史区高 | 图片框 | 卡片 | 竖向滚轴 |
|---|---|---|---|
| 100 / 140 | 120×120 | 132×161 | 有 |
| 230 / 277 / 394 / 400 / 700 | 120×120 | 132×161 | 无 |

- **图片尺寸恒定**：面板单独测 96/120/200/300/500/800 六种高度，以及真实 `MainWindow`
  里 `v_splitter.setSizes` 四档，图片框一律 120×120、卡片一律 132×161。
- **历史区高度可一直往下拖**：最小能拖到 **113px**（面板 `minimumSizeHint` 162×113），
  原来是 221px 就到底了。想要更低可以把 `MIN_VIEW_H` 调小，或把
  `main_window` 里的 `v_splitter.setCollapsible(1, False)` 改成 `True` 允许完全收起。
- **滚轴行为**：竖轴按需（视口 < 169 时出现），横轴按需（内容宽度 > 视口时出现，
  实测面板宽 400 + 8 条记录时 `maximum() = 726`）。
- 验证脚本 `_verify_hist.py` / `_verify_hist_win.py` / `_verify_scroll.py` 与截图均已删除。

### 6.3 判定显示：`G` / `NG` / `?`（m01391，已实测）

用户原话：「0要对应显示G，1要对应显示NG」。

| 情形 | `output_value` | 界面文字 | 配色 |
|---|---|---|---|
| 数字命中目标集合 | `1` | `NG` | 红 `#e74c3c` |
| 数字不在目标集合 | `0` | `G` | 绿 `#2ecc71` |
| **识别失败**（`circle_not_found` / `no_number` / `read_failed` / `error`） | `0` | `?` | 橙 `#e67e22` |

- **唯一真源**：`core/models.py` 的 `RecognitionResult.output_text` 只读 property。
  界面四处都取自它：`ui/widgets/result_panel.py`（大方框）、`ui/widgets/history_panel.py`
  （`数字 → G/NG` 文字 + 卡片边框色）、`ui/overlay.py`（图像上的大字与 ROI 框色）、
  `ui/main_window.py`（状态栏）。
- ★ **识别失败必须单独显示 `?`**：失败时 `output_value` 也是 `0`，照搬映射会显示成绿色的
  `G`，等于把「没看清」误报成良品（设计文档反目标 A2 / 缺陷 D1）。
- ⚠️ **只改显示，不改数据**：串口仍发裸 `b'1'`/`b'0'`（`app/controller.py`），
  CSV 里仍是整数 `1`/`0`（`infra/csv_logger.py`）。Arduino 与历史数据格式不受影响。
- **【推断】**反推业务语义：`TARGET_NUMBERS` 是**不良品编号**（命中即 NG）。
  若实际相反，把 `output_text` 里的 `G`/`NG` 两个字符串对调即可。
- 离屏验收 `_verify_gn.py`（已删）26 项全过：三态文字、三态底色、G/NG 边框不同色、
  叠层绿色像素 G 图 5430 > NG 图 0。

### 6.4 ★ 每张图必处理、必发一个串口字节（m03412，已实测）

用户原话：「我需要确保每一张图片都要识别到，对于每一张图片都需要发出对应的处理信号」。

**修复前有两条路会「静默吞掉」一张图**：

| 吞掉的地方 | 原来怎么吞的 | 后果 |
|---|---|---|
| `app/workers.py` 的推理队列 | `queue.Queue(maxsize=1)`，满了就 `get_nowait()` 丢**最旧**帧 | 界面闪过、但没识别、没进 CSV、没发串口 |
| `infra/image_source.py:_tick` | `if img is not None:` 才发帧，`cv2.imread` 失败直接跳过 | 坏文件凭空消失，一张图对应零条记录 |

**现在的机制（三条一起才成立）**：

1. **推理队列不设上限**（`queue.Queue()`，`submit()` 直接 `put`，永不丢）。
2. **一帧在飞**：`InferenceWorker.frame_processed` 每帧发一次（成功/失败都发，
   放在 `finally` 里，UI 槽抛异常也放行）→ `AppController._ack_source()` →
   `current_source.frame_done()` → 输入源才去取下一帧。
   - `FolderSource` 的定时器改成 **single-shot**：发一帧就停表，收到 `frame_done` 再上弦。
     所以 `poll_interval_ms` 的语义变成了「**上一帧处理完后再等多久**」，不是固定帧率。
   - `CameraSource` 用 `threading.Event`：读完一帧 → 发出去 → `self._ack.wait()` →
     收到 `frame_done` 才读下一帧。**不再按 fps 闷头读**（那样缓冲区里的帧会被顶掉）。
3. **打不开的图也上报**：`BaseSource.read_failed(name)` → `AppController._on_read_failed`
   造一条 `status="read_failed"` 的 `RecognitionResult`，走**同一条**分发链
   （界面 `?` + `history_panel` 的「无图」占位 + CSV 一行 + 串口一个 `'0'`）。

**每帧必发串口**：`AppController._on_result` 里删掉了 `send_on_change_only` 分支，
只要串口是开的，每个结果都发一个字节。理由：固件是「收到 `'1'` 吹一次、收到 `'0'` 立刻关」，
若只在变化时发，**连续两颗 NG 的第二颗就不会吹**。`SerialPanel` 的「仅变化时发送」
勾选框已删除，换成一行说明「每张图发 1 字节：`'1'`=NG 吹阀 / `'0'`=G 放行」；
`config.yaml` 的 `serial.send_on_change_only` 键也删了。

**对账口径**（`AppController`）：

```
frames_in   进来几张       （_on_frame / _on_read_failed 各 +1）
results_out 出去几个结果   （_on_result 每次 +1）
pending     = frames_in - results_out   ← 正常恒为 0；界面状态栏显示「待处理 N」
```

**验收【已实测】**（`_verify_every_frame.py`，临时，已删，25 项全过）：

| 用例 | 文件数 | frames_in | results_out | 串口字节 | CSV 行 | 队列残留 | 最大积压 |
|---|---|---|---|---|---|---|---|
| A `project_0\data\test3`，`interval_ms=0`（最快，最容易触发丢帧） | 12 | 12 | 12 | 12 | 12 | 0 | 0 |
| B 1 张好图 + 1 张坏图 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |

- A 还逐条比对了「串口字节序列」与「CSV 的 `output_value` 序列」，完全一致：
  `[1,1,1,1,1,0,1,0,1,0,1,0]`
- A 的逐张结果（与 §5.3 的旧记录一致）：`12/19/20/25/37/41/43` → NG，
  `4.png` = `no_number`，`42/7/T2..-5` → G
- B 的坏图：`status=read_failed`、进了 CSV、也发了 `'0'`
- UI 冒烟 `_verify_ui_smoke.py`（已删，12 项全过）：状态栏 `待处理 0` 正常；
  喂一条结果后变 `已处理 1 / 命中 1 / 待处理 0`；坏图 `frame=None` 也能进历史（「无图」占位）

**⚠️ 未实测的部分**：`CameraSource` 的新等待逻辑没有硬件，只做过代码审读 ——
真机联调时先确认「按 fps 设置不再丢帧」。另外串口**没打开**时不会发字节（这是硬件状态，
不是丢帧），界面状态栏会显示「未连接」。

> 语义变化提醒：`poll_interval_ms` 以前是固定节拍，现在是「处理完再等这么久」。
> 想尽快跑完就把间隔设小（界面下限 50 ms）；想慢慢看就设大。

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
| ④ | ~~`config.yaml:44-50`~~ | ~~`source:` 段**根本没被读取**；`SourcePanel` 里硬编码 15fps / 300ms / loop~~ | ✅ **已修**（见 §7.1） |
| ⑤ | `config.yaml:44-45` | `serial.last_port` / `baudrate` 未被使用 | 接线到 `SerialPanel` |
| ⑥ | `infra/image_source.py:3` | `from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal` → **`infra/` 不是纯 Python 层**。`core/` 是干净的 | 至少知情；要么下沉到 app/ui，要么接受 |
| ⑦ | `core/models.py:19` + `ui/widgets/history_panel.py:66` | `frame` 存**整帧**，`MAX_ITEMS = 200` → 最多 **200 张整帧常驻内存** | 存缩略图 |
| ⑧ | `core/pipeline.py:45` | 调 `decider.decide(num)` 没传 `status`，而 `decision.py:23` 有这个参数（默认 `"ok"`）→ 参数形同虚设 | 传 `res.status` |

> ✅ **已从「待修」里划掉两条**（m03412）：推理队列丢帧、坏图被 `if img is not None` 跳过 ——
> 两条都会「静默吞掉一张图」，现已修，机制与实测见 **§6.4**。

### 7.2 ✅ 已修：丢帧 + 坏图被跳过（m03412）

| 原来 | 现在 |
|---|---|
| `InferenceWorker` 的 `queue.Queue(maxsize=1)`，满了丢最旧帧 | 队列不设上限 + 一帧在飞（`frame_processed` → `frame_done()` 背压） |
| `FolderSource._tick` 的 `if img is not None:` 让坏文件静默消失 | `read_failed(name)` 上报 → 造一条 `status="read_failed"` 结果，照常进界面/CSV/串口 |
| `send_on_change_only` 可以勾上，连续两颗 NG 的第二颗不吹 | 该选项已删除，**每帧必发一个字节** |

细节与 25 项验收数字见 **§6.4**。

### 7.1 ✅ 已修：输入源面板不再硬编码，循环默认不勾选（m01887）

**用户要求**：「修改前端界面的默认配置，默认不勾选循环」。

- `E:\Python Project\ocr_system\ui\widgets\source_panel.py`：`SourcePanel.__init__(self, config: dict = None)`，
  从 `config["source"]` 读初值 —— `type`（选 radio）/ `folder_path`（填路径框）/
  `camera_index` / `fps` / `poll_interval_ms` / `loop`；**缺键时兜底 `folder` / "" / 0 / 15 / 300 / false**。
  `self.loop_check.setChecked(bool(cfg.get("loop", False)))` —— 原来是硬编码
  `setChecked(True)`。界面上改动**不写回** config.yaml。
- `E:\Python Project\ocr_system\ui\main_window.py:38`：`SourcePanel()` → `SourcePanel(config.get("source", {}))`。
- `E:\Python Project\ocr_system\infra\image_source.py:23`：`FolderSource.__init__` 的
  `loop` 默认值 `True` → **`False`**（控制器一直显式传参，改默认值只为消除隐患）。
- `E:\Python Project\ocr_system\config.yaml`：`source:` 段加注释说明它是面板初值、`loop` 默认 false。
  值仍是 `type: folder` / `fps: 15` / `poll_interval_ms: 300` / `loop: false`。

**数据链路（已实测）**：`loop_check.isChecked()` → `SourcePanel._start()` 的
`cfg["loop"]` → `app/controller.py:86` `loop = cfg["loop"] and t == "folder"` →
`FolderSource(path, interval_ms, loop)`。不勾选时 `FolderSource` 放完一遍就
`finished`，勾上才 `self._idx` 归零从头再来。

**验收**（`_verify_loop.py`，临时，已删，EXIT=0，18 项全过）：默认不勾选；
`config` 里 `loop: true` 时勾上；`type: camera` / `camera_index: 2` / `fps: 30`
都生效；`_start()` 发出的 `cfg["loop"]` 与勾选一致；真实 `MainWindow` 里未勾选；
控制器把 `False`/`True` 原样透传给 `FolderSource`；`FolderSource` 默认值为 `False`；不传 `config` 时向后兼容。

---

## 8. ✅ 已解决：模型加载失败（用户报的「点加载模型显示加载失败」）

用户报告：运行 `test/run_app.py`，点「加载模型」→ 界面 **加载失败**，控制台反复刷
`Model files already exist. Using cached files. To redownload, please delete the directory manually: ...PP-OCRv6_small_rec`。

### 8.1 曾经的两个误判（**已推翻，别再往这两个方向查**）

- ❌ **不是 OS 级 ACL 损坏。**
  当时只在 DSH 受限会话里测，看到 `PermissionError [WinError 5] 拒绝访问` 就下了「目录 ACL 坏了」的结论。
  【已实测】去掉沙箱重跑同一段读取代码：**15 个模型目录全部可读**，`PP-OCRv6_small_rec` 里 5 个文件齐全，`.paddlex` 也可写。
  → 那是 **DSH 沙箱**在挡沙箱外路径（沙箱进程的令牌拿不到那些目录的 ACE，只有继承未被打断的
  `PP-LCNet_x1_0_doc_ori` 恰好能读）。**模型文件从来没有损坏过。**
  判定方法（可复用）：**同一个读操作，加 `danger-full-access` 再跑一次**。能读 → 是沙箱；仍不能读 → 才是 OS ACL。
- ❌ **不是 paddlex 下载失败。**「Model files already exist」只是说明走了本地缓存，是噪音不是错误。

### 8.2 真正的四个原因（缺一不可，均已修复）

| # | 缺什么 | 报错 |
|---|---|---|
| ① | `pypdfium2` | `DependencyError: PDFReaderBackend is not ready for use ... pypdfium2` |
| ② | `opencv-contrib-python` | 同上一条。**`opencv-python` 不算数**：paddlex 检查的是 `opencv-contrib-python` 这个**发行版名**（`readers.py:27` 也是从 contrib 导入 cv2） |
| ③ | `paddlex` 版本太旧（3.4.3） | `ClassNotFoundException: PP-OCRv6_small_rec is not registered on BasePredictor` —— 3.4.3 的注册表只有 v5 及更早；`configs/modules/text_recognition/PP-OCRv6_small_rec.yaml` 是 3.7.2 才有的 |
| ④ | `python-bidi` | `DependencyError: TextRecRunnerPredictor is not ready for use ... python-bidi`（v6 走 runner 推理器） |

关键：①②④ 这三样 paddlex **只在 extras（`cv` / `ocr-core` / `ocr` / `base`）里声明**，
所以 `dependencies` 里裸写 `"paddlex"` **必然缺**，必须自己列出来。

触发点：`paddlex/inference/common/batch_sampler/image_batch_sampler.py:52`
`self.pdf_reader = PDFReader(zoom=PDF_RENDER_SCALE)` 是**无条件**执行的，
所以**任何** `create_model()` 都会先踩 ①②。

### 8.3 修复动作（已执行并验证）

```
paddlex                3.4.3 → 3.7.2
numpy                  2.5.4 → 2.3.5    # paddlex 3.7.2 要求 numpy<2.4（原约束不可能满足）
opencv-python          移除             # 与 contrib 争抢同一个 cv2/ 目录，先装谁谁生效
+ opencv-contrib-python 5.0.0.93        # 与 opencv-python 同版本，是其超集
+ pypdfium2             5.14.0
+ python-bidi           0.6.11
```
`pyproject.toml` 已同步、`uv lock` 已刷新（Resolved 66 packages）、`uv sync` 显示已一致。

【已实测】验收 —— 走 **GUI 真实链路**（`AppController.load_models` → `EngineLoadWorker` → `EngineManager`）：
```
engine_status: ok=False  msg=正在加载识别模型 PP-OCRv6_small_rec …
engine_status: ok=False  msg=正在加载方向模型 PP-LCNet_x1_0_textline_ori …
engine_status: ok=True   msg=模型已加载
```
另单独验证：`create_model('PP-OCRv6_small_rec')` OK 1.6s、`create_model('PP-LCNet_x1_0_textline_ori')` OK 0.3s。

> ⚠️ 上面这两行 `ok=False  msg=正在加载…` 当时被我当成正常输出，**其实是 bug**：
> 界面会把它们渲染成红色的「加载失败」。见 §8.7（已修）。

### 8.4 顺手修掉的两个「诊断障碍」（这才是当初看不懂的原因）

- `ui/widgets/model_panel.py:55` 原本是 `msg[:30]` —— **把真实异常截断了**，所以界面上只剩「加载失败」。
  现改为：标签显示异常**最后一行**，完整内容放 **tooltip**。
- `app/workers.py` 的 `except` 只有 `str(e)`，现加 `traceback.print_exc()`，完整堆栈进控制台。

### 8.5 遗留的环境限制（**不是代码 bug，别去修代码**）

- ~~DSH 沙箱下读不到 `C:\Users\14734\.paddlex`~~ → **已通过把模型搬进项目内解决**（见第 3 节）。
  现在 `models/` 在工作区内，受限会话也能读，`test/run_app.py --check` 的模型检查项从 WARN 变成 OK。
- 沙箱下 `.venv` 是**只读**的，`uv pip install` 会 `Failed to create directory ... 拒绝访问`，
  装包必须用一次性非受限执行。
- uv 默认缓存在 `C:\Users\14734\AppData\Local\uv\cache` 同样被拒，
  需把 `UV_CACHE_DIR` 指到工作区内（本项目用 `.uv-cache/`，已加入 `.gitignore`）。

### 8.6 模型读取位置（2026-10-16 变更，**这是现在的正确答案**）

模型**不再**从 `~/.paddlex` 读，而是从项目内的 `models/official_models/` 读。
机制、依据与副作用见第 3 节「模型缓存位置与本地清单」。

### 8.7 「先闪一下加载失败，再变已加载」（用户报，已修）

**现象**：点「加载模型」→ 先红字「加载失败: 加载识别模型 …」→ 再绿字「已加载」。

**根因（单一）**：进度和终态共用了一条带 `ok` 布尔的信号。
`app/controller.py` 原来是
```python
self._load_worker.progress.connect(lambda s: self.engine_status.emit(False, s))
self._load_worker.done.connect(self.engine_status.emit)
```
而 `ui/main_window.py:125` 是 `engine_status → model_panel.set_loaded`，
`set_loaded(ok=False, …)` 的分支就是**加载失败**。
于是 `core/engine.py:18/:26` 那两句进度文案（「加载识别模型 X …」）被渲染成失败。

**顺带修掉的第二个 bug**：`set_loaded` 开头无条件 `btn_load.setEnabled(True)`，
进度也走这条路 → **加载还没结束按钮就已可用**，能重复点击触发第二个 worker。

**修法**：进度与终态分成两条信号。
- `app/controller.py`：新增 `engine_progress = pyqtSignal(str)`，进度接它，`engine_status` 只留终态
- `ui/widgets/model_panel.py`：新增 `set_progress(msg)`（橙字「● 加载中… …」，**不放开按钮**）；`_on_load` 改为调用它
- `ui/main_window.py`：`controller.engine_progress.connect(model_panel.set_progress)`

**实测（离屏，三用例，全过）**：
```
成功路径  [0] ● 加载中… 加载识别模型 PP-OCRv6_small_rec …
          [1] ● 加载中… 加载方向模型 PP-LCNet_x1_0_textline_ori …
          [2] ● 已加载                      判定 OK
失败路径  [0] ● 加载中… 加载识别模型 PP-OCRv6_small_rec …
          [1] ● 加载失败: 模型不存在：PP-OCRv6_small_rec    判定 OK（失败仍能报出原因）
真实路径  [0] ● 加载中…  [1][2] 两个模型  [3] ● 已加载      判定 OK
加载中按钮全程保持禁用
```

---

## 9. 【未验证】的部分 —— 别当成已完成

**2026-10-16 更新：单帧端到端已跑通**（真实模型 + `project_0\data\test3` 的 12 张真实样张，
走 `EngineManager → Preprocessor → Recognizer → DecisionMaker → OcrPipeline`，**11/12 张 `ok`**）。
所以下面这些**已经不再是「从未执行」**：

- ✅ `EngineManager` 的模型缓存（同一次进程内只 `create_model` 一次）
- ✅ `Recognizer.recognize` 的角度循环、方向分类转 180°、**聚合选果**（见 §5.3）
- ✅ `DecisionMaker.decide` 的 1/0 判定（`hit` / `output_value` 实测一致）
- ✅ `OcrPipeline.run_on_image` 的端到端结果（`status` / `number` / `confidence` / `angle` / `elapsed_ms` 全部有值）

**仍然没验证过**：

- ~~`infra/serial_service.py` 的实际收发~~ → ✅ **已实测（m03833）**：打开 COM 口、按每帧发字节，NG 帧 Arduino 板载 LED 亮
- ~~Arduino 侧完全是未验证的~~ → ✅ **固件已烧录、行为符合预期**（用户 m03767 确认）
- ~~「Python 发字节 → Arduino」这条链路~~ → ✅ **已打通（m03833）**
- **气动部分**：只看到 LED 亮 → **阀是否真的吹气、吹得动那颗料，未验证**（需接阀 + 气源）
- `PULSE_MS = 100` 对**实际喷气嘴**合不合适（固件注释说典型电磁阀 10~50ms）
- `'0'` 提前关阀会不会掐断脉冲（§5.4.1，取决于帧间隔，当前 220ms 不触发）
- **DTR 复位是否吞掉「第一颗」判定**：整体流程不受影响，但没单独数过亮灯次数
- 全部 GUI 交互（除「加载模型」「开始/停止」外的按钮没点过）
- 实时视频流（只跑过离屏、单帧、静态样张；`CameraSource` 的新等待逻辑**无硬件未实测**）
- `test/test_rename.py` 的重命名行为

**所以：「图像 → OCR → G/NG → 串口 → 板子输出」这条主链已经实测跑通；
只剩「气动阀真正吹料」与「GUI 其余按钮」未经真机验证。**

---

## 10. 下一步

1. ~~灌一帧真实图像跑通单帧端到端~~ ✅ **已完成（2026-10-16）**，见 §9
   - 实测：`E:\Python Project\project_0\data\test3` 12 张 → **11 张 ok、1 张 no_number**（`4.png`）
   - 每张耗时约 222–231ms（首张约 1925ms 含模型加载）；命中 7 张（12/19/20/25/37/41/43）
2. ~~决定 `20.png` 这个回归怎么处理~~ ✅ **已修**（m01818，边际分求和）→ 见 §5.3.1
3. ~~设计文档待裁定问题~~ ✅ **Q1–Q6 全部关闭**（m03236 / m03412 / m03646）→ 文档 §12 无待决项
4. ~~串口报文格式~~ ✅ 已由固件定案（裸 `'1'`/`'0'`）→ 见 §5.4.1
5. ~~Arduino 固件烧录~~ ✅ **已烧录，行为符合预期**（m03767）
6. ~~真机联调：Python 侧驱动那块板子~~ ✅ **已打通（m03833）** —— 跑图后 NG 帧板载 LED 亮
7. **接气源 + 喷气嘴，确认阀真的能吹掉料** ← 现在最后一段没验的。顺带确认：
   (a) `PULSE_MS = 100` 对实际喷气嘴合不合适（固件注释：典型电磁阀 10~50ms）；
   (b) **`'0'` 提前关阀会不会掐断脉冲** —— 帧间隔 < 100ms 时才会暴露（§5.4.1），
       届时考虑改固件为 `if (!pulsing) { 关阀; }`
   (c) DTR 复位是否吞掉「第一颗」：数「界面已处理 N」与「板子亮灯次数」是否相等
8. `serial.last_port` / `baudrate` 要不要接线到 `SerialPanel`（缺陷 D3 另一半）
9. 再决定要不要清掉第 7 节剩下的待修缺陷（①CSV 截断、②双重 shutdown、③有效范围重复定义、⑤串口配置未接线、⑦整帧常驻内存、⑧`decide` 的 status 参数）
10. GUI 全流程点一遍（除「加载模型」「开始/停止」外的按钮都没点过）

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
| m00299 | 用户：「生成一个设计文档md」→ `docs/superpowers/specs/2026-10-15-ocr-system-design.md`（14 节）；builder-check 返回 8 问（Q1–Q6 待用户裁定） |
| m00370 | 用户：「创建git本地仓库然后提交」→ 提交 `ca39316`（38 文件，含 .gitignore/.gitattributes/logs/.gitkeep） |
| m00392 | 用户：「在test目录下生成一个脚本，运行这个脚本能够启动这个项目用于测试」→ `test/run_app.py`（334 行），提交 `969cac3` |
| m00435 | 用户报告：点「加载模型」显示加载失败，控制台刷 `Model files already exist ... PP-OCRv6_small_rec` |
| — | **一度误判为「OS 级 ACL 损坏」**；随后用「同一读操作 + `danger-full-access` 重跑」推翻：15 个模型目录全部可读 → 是 DSH 沙箱，模型文件从未损坏 |
| — | 真根因共四条：paddlex 只在 extras 里声明 `opencv-contrib-python` / `pypdfium2` / `python-bidi`；且 paddlex 3.4.3 的注册表里**根本没有 `PP-OCRv6_*`** |
| — | 修复：paddlex 3.7.2、numpy 2.3.5、opencv-contrib-python 5.0.0.93（移除 opencv-python）、pypdfium2 5.14.0、python-bidi 0.6.11；`uv.lock` 已刷新 |
| — | 顺手修掉两处「诊断障碍」：`model_panel.py` 的 `msg[:30]` 截断、`workers.py` 只打印 `str(e)` 无堆栈 |
| — | 【已实测】走 GUI 真实链路 `AppController.load_models` → `engine_status: ok=True 模型已加载`；第 8 节据此重写为本文件当前内容 |
| m00641 | 用户：「能不能将所有模型都放在项目目录内，然后直接读取」→ 15 个模型目录（477.1 MB）复制到 `models/official_models/`；`main.py` + `test/run_app.py` 设 `PADDLE_PDX_CACHE_HOME`；`models/` 加 gitignore；`--check` 从 2 个 WARN 变成全部通过 |
| m00749 | 用户：「历史模块添加动态调节高度，以及清除历史按钮和功能，角度选择我需要每个10度都有」→ ① `HistoryPanel` 去掉固定 190px，缩略图随高度等比重缩放（56~240）② 新增「清除历史」按钮 + `cleared` 信号，状态栏统计一并归零 ③ `AnglePanel` 改为 -180°~180° 每 10° 共 37 个复选框（原 10 个）④ `main_window` 历史区改放进竖直 `QSplitter`，右列包 `QScrollArea`（否则 37 个复选框把历史区压死）⑤ `config.yaml` 的 `angles` 去掉不在网格上的 -45/45 |
| — | 【已实测】`_verify_ui.py` 离屏验收：37 个角度框、全选=37、默认=8；历史区 195→394→120px 时缩略图 126→240→56px；清除后计数归 0、状态栏统计归零、再追加正常；`compileall` 退出码 0；`test/run_app.py` 真实启动 22 秒仍存活无异常。提交 `17e654e` |
| m00913 | 用户：「角度选择再修改一下，添加负号勾选，然后只显示0-180，步长是10」→ `AnglePanel` 只列 0~180 每 10° 共 19 格；新增「负号（每个勾选角度同时尝试 -θ）」复选框；`selected_angles()` 负责把正值展开成 ±（0 不重复、-180 与 180 合并）；`config.yaml` 注释与 `core/recognizer.py` 的 `RecognizerConfig.angles` 默认值同步去掉 -45/45 |
| — | 【已实测】`_verify_angle.py` 离屏验收：19 格 + 无负数格；config `[-90,-60,-30,0,30,60,90,180]` → 勾 `[0,30,60,90,180]` + 负号 → 展开回原 8 个角度；取消负号→5 个；全选→36 个（有 180 无 -180）；仅 0°→`[0]`；反选→空；默认→复位；批量操作只发 1 次信号；含 -45/45 的旧配置被丢弃。`_verify_win.py`：角度面板最小高 236→167px，右列无横向滚动条、历史动态高度仍生效。提交 `7b31b50` |
| m01073 | 用户：「前端角度选项还要修改：0度和180度独立出来不受负号影响，因为-0度-180度没意义」→ `AnglePanel` 拆成两组：**固定角度 0°/180° 单独一行、永不受「负号」影响**；旋转角度 10°~170° 共 17 格由「负号」控制。因为旋转组里没有 0/180，展开 `-a` 永不撞车，`selected_angles()` 里的特例（`if a != 0`、`discard(-180)`）**全部删掉** |
| — | 【已实测】`_verify_angle2.py` 离屏验收：固定组 `(0,180)` / 旋转组 17 格 / 总数 19；config 旧值解析结果与改动前**逐位相同** `[0,-30,30,-60,60,-90,90,180]`；负号开↔关时 0° 与 180° 恒在且恒不带负号；只勾 0°+负号→`[0]`、只勾 180°+负号→`[180]`（无 -0°/-180°）；全选+负号=36、无负号=19；批量按钮各只发 1 次信号；含 -45/45 旧配置仍被丢弃。面板最小尺寸 358x188（原 376x167），`compileall` 退出码 0。提交 `3a0fea6` |
| m01143 | 用户：「历史记录区里的图片框会因为我拉高历史记录区的高度而变化，我需要固定图片的大小」→ 推翻 m00749 的「缩略图随高度缩放」设计：`HistoryItem.THUMB_W = THUMB_H = 120`、卡片固定 132×161；删掉 `set_thumb_height`/`MIN_THUMB_H`/`MAX_THUMB_H`/`HistoryPanel.resizeEvent`/`_resize_timer`/`_desired_thumb_h`/`_apply_thumb_height`；改为 `MIN_ROW_H = THUMB_H + 44 = 164` 并 `scroll.setMinimumHeight(MIN_ROW_H)`；`main_window` 的 `setSizes` 由 `[660, 190]` 改 `[640, 230]`。**区域仍可拖高，图片尺寸恒定**（见 §6.2） |
| — | 【已实测】`_verify_hist.py`（面板单独 120/200/300/480/700 五种高度）+ `_verify_hist_win.py`（真实 `MainWindow` 里 `v_splitter.setSizes` 四档，实际落到 221/277/394/221）两次结果完全一致：图片框恒 120×120、卡片恒 132×161；`HistoryPanel.minimumSizeHint` 高 221；`compileall` 退出码 0。提交 `97d482b` |
| m01221 | 用户：「但现在历史记录区不能一直向下拉了，我需要可以一直向下拉，然后有一个滚轴」→ 这是我 m01143 引入的回归：`scroll.setMinimumHeight(164)` 把面板最小高度顶到 221px，分割条拖到底就停住。修：`MIN_VIEW_H = 56`（面板最小 113px，实测能拖到 113）+ `setVerticalScrollBarPolicy(ScrollBarAsNeeded)`（矮了缩略图被裁切，靠竖向滚轴看全）。`HistoryItem` 尺寸一点没动 |
| — | 【已实测】`_verify_scroll.py`：面板 100/140px → 竖向滚轴有、230/400px → 无；面板宽 400 + 8 条记录 → 横向滚轴有（`maximum()=726`）、宽 1200 → 无；96/120/200/300/500/800 六种高度下图片框恒 120×120、卡片恒 132×161；真实 `MainWindow` 里能拖到 113px（原 221px）；`compileall` 退出码 0。提交 **`b960dc0`** |
| m01277 | 用户：「更新到本地git」→ 提交 `config.yaml`（用户自己改的两处：`recognizer.early_exit_conf` 0.98→0.99、`source.loop` true→false）为 **`3ef586b`**。仓库无远程，分支 `main` |
| m01286 | 用户：「更新记忆和技术文档」→ 设计文档 `docs/superpowers/specs/2026-10-15-ocr-system-design.md` 升到 **v1.2**：§11 两个「阻塞项」改写为 ✅ 已解决（阻塞项 1 推翻为 DSH 沙箱问题、附可复用判据；阻塞项 2 记为三个真实根因表 + §11.3 诊断障碍 + §11.4 验证状态）；新增 §8.1 角度面板规则 / §8.2 历史区与缩略图规则；§10 补 J7–J10；§12 的 Q4 从「环境权限」改写为「离线是否硬约束」；§13 增设第 8/9 条验收；§14 实现状态表重写；**新增 §15 环境与依赖（已实测）**。本文件 §12 时间线补齐 m01143–m01286 |
| m01391 | 用户（配「检测结果」面板截图）：「这里修改一下，0要对应显示G，1要对应显示NG」→ 新增 `core/models.py` 的 `RecognitionResult.output_text` 只读 property 作为**唯一真源**（0→`G`、1→`NG`、识别失败→`?`），界面四处统一取自它：`result_panel`（大方框）、`history_panel`（文字 + 边框）、`overlay`（图像上的大字与框色）、`main_window`（状态栏）。配色改为 **G 绿 / NG 红 / ? 橙**（原先 `output_value==1` 是绿色，本次**推翻**）。**串口与 CSV 不动**，仍是原始整数 `1`/`0` |
| — | 【已实测】`_verify_gn.py` 离屏验收 26 项全过：四类样本（良品 / 不良 / 没找到圆 / 没识别出数字）的 `output_text`、面板文字、面板底色、历史卡片文字与边框色；`output_value` 仍是 0/1 且 `output_text` 无 setter；叠层绿色像素 G 图 5430 > NG 图 0；`compileall` 退出码 0。截图确认 `NG` 在 80×80 方框内不被挤（两字降到 38px） |
| m01529 | 用户（配角度面板截图）：「面板上10-170增加到5-175，步长为5，然后添加一个下拉选项，可以勾选步长为5,10,15,20,30（勾选的值就是180/5,180/10以此类推）」→ `AnglePanel` 重写为 263 行：`STEP_OPTIONS=(5,10,15,20,30)` + `DEFAULT_STEP=5` + `COLUMNS=5`；新增类方法 `rotation_angles(step) = list(range(step,180,step))`、属性 `step`；新增 `QComboBox`（文案 `步长 5°（180 ÷ 5 = 36 等分）` … `步长 30°（180 ÷ 30 = 6 等分）`）→ `_on_step_changed` 重建网格（`_rebuild_grid` + `_sync_labels`），**换步长时保留仍在新网格上的勾选、取消掉出网格的并打印提示**；「默认」按钮只复位勾选与负号、**不动步长**；负号与「全选」按钮的文案跟着网格范围/数量走 |
| — | 【已实测】`_verify_angle3.py` 离屏验收 60 余项全过（含真实 `MainWindow`）：五档步长旋转格数 35/17/11/8/5、总数 37/19/13/10/7；下拉文案与数据 `[5,10,15,20,30]`；默认态 `[0,-30,30,-60,60,-90,90,180]`；config 旧值解析**逐位不变**；负号开关不影响 0°/180°；全选无负号 37 个 / 有负号 72 个；仅 0°→`[0]`、反选→空、默认→复位；步长 5→30 保留 30/60/90、5/25 被丢弃；批量与换步长各只发 1 次信号。面板最小尺寸 **430×250**（步长 5）/ 430×142（步长 30）；右列内容最小 **504×939**、视口 504×643、竖向滚动条有、横向无。`compileall` 退出码 0 |
| m01626 | 用户贴出新的「结果输出逻辑」并要求整合进 `recognizer.py` → **`_aggregate_by_number(candidates)`**（按数字分组，`agg=Σscore / max=最高单次分 / votes=票数`，按 `(agg,max,votes)` 降序）+ `recognize()` 改为**跑完全部角度后按聚合分选结果**，返回该数字所有票里置信度最高的那次角度。**删除旧版的 `angle == 0 and score >= 0.98` 早退**（会丢票）；`CONF_THRESHOLD` 0.6 → **0.5**（只做准入）；新增 `debug_aggregate` 开关（config 里暂设 true）；`early_exit_conf` 保留字段但标注已废弃；`core/recognizer.py` 96 → 145 行 |
| — | 【已实测】`_verify_agg.py`：T1–T11 用假引擎（`build_variants` 返回带角度标记的 5×5 图，中心像素 180° 旋转不变、角像素判是否被转）逐条验证聚合排序、聚合分/最高分/票数、**多角度互证胜过单次高分**（12×2 票胜 25×0.99）、**不再早退**（ori/rec 各调 3 次、角度集合正确）、阈值 0.499/0.5 边界、超范围跳过、丢 0、清洗非数字、方向分类转 180°（含 `label_names` 兜底）、平局三档规则、`best_angle` 取最高分那次、空候选 → None；T12 真实模型 + 真实样张：`12.png` → 聚合 `12: sum=2.9920 votes=3` 胜过 `2: 0.9918` → `('12', 0.9995, 0°)`；`37.png` → `37: sum=0.9788 votes=1`（**仅 -30° 认出**）→ `('37', 0.9788, -30°)`。`test/run_app.py --check` 全部通过；`compileall` 退出码 0 |
| — | 【已实测】★ **单帧端到端首次跑通**（`_e2e.py`，真实模型走 `EngineManager → Preprocessor → Recognizer → DecisionMaker → OcrPipeline`，`project_0\data\test3` 12 张样张，默认 8 个角度）：**11/12 ok**、1 张 `no_number`（`4.png`）；命中 6 张（12/19/25/37/41/43）；成功耗时 224–239ms（首张 1925ms 含模型加载）；`hit` 与 `output_value` 完全对应（命中 → `1` → `NG`，未命中 → `0` → `G`，失败 → `?`）。**但 `20.png` 被判成 `2`（demo 读作 `20`）→ 见 §5.3.1**。提交 **`baca498`** |
| m01818 | 用户：「按照修法1修改」→ 聚合分由 `Σscore` 改为 **`Σ(score - conf_threshold)`**（边际分），并**四舍五入 6 位**去掉浮点尾差（否则「边际相同→比票数」这一级会被 `0.9+0.9-1.0` 与 `0.9+0.7+0.7-1.5` 的 1e-16 误差架空）；`debug_aggregate` 的打印前缀 `sum=` 改成 `margin=`；`_aggregate_by_number` 增加 `threshold` 参数 |
| — | 【已实测】`_verify_margin.py` 全过（T1–T13）：T1 边际聚合分 `[0.7, 0.55, 0.49]`；T2 **两张 0.8 的票胜一张 0.99**（0.6 > 0.49，多角度互证的性质保住了）；T3 三角度全跑（无早退）；T4 0.499 拒 / 0.5 收；T5 超范围跳过；**T5b 用 `20.png` 的真实票复现：旧规则选 `2`（留证）、新规则 `20` 边际 0.9990 > `2` 的 0.5871**；T6–T11 丢 0 / 清洗非数字 / 转 180° / 平局三档 / `best_angle` / 空候选；T12 真实模型 `20.png → 20`、`12.png → 12`、`37.png → 37`；**T13 完整 `OcrPipeline` 跑 12 张 → 11/12 ok，命中 7 张（比修前多出 `20.png`）**，`20.png` 现在是 `conf=0.9997 angle=-90°` |
| m01887 | 用户：「修改前端界面的默认配置，默认不勾选循环」→ `SourcePanel.__init__(self, config: dict = None)` 从 `config["source"]` 读初值（`type`/`folder_path`/`camera_index`/`fps`/`poll_interval_ms`/`loop`，缺键兜底 `folder`/""/0/15/300/**false**），**循环默认不勾选**（原为硬编码 `setChecked(True)`）；`ui/main_window.py:38` 改为 `SourcePanel(config.get("source", {}))`；`FolderSource.__init__` 的 `loop` 默认 `True`→`False`；`config.yaml` 的 `source:` 段加注释说明它是面板初值。**缺陷清单 ④ 就此关闭**（`source:` 段以前根本没人读）|
| — | 【已实测】`_verify_loop.py` 18 项全过：默认不勾选；`config` 里 `loop: true` 时勾上；`type: camera` / `camera_index: 2` / `fps: 30` 生效；`_start()` 发出的 `cfg["loop"]` 与勾选一致；真实 `MainWindow` 里未勾选；控制器把 `False`/`True` 原样透传 `FolderSource`；`FolderSource` 默认值 `False`；不传 config 向后兼容。`compileall` 退出码 0。提交 **`e3a4468`** |
| m03236 | 用户：「更新git和设计文档还有记忆，arduino文件夹也提交」→ 把用户自己写的 Arduino 固件 `arduino/sketch_oct19a/sketch_oct19a.ino`（43 行）**纳入版本库**，并据此改写文档：**串口报文格式不再是未决项** —— 固件认裸 `'1'`/`'0'`，`'1'` 开**喷气阀** `PULSE_MS=100ms` 自动关、`'0'` 立即关（放行）、`Serial.begin(115200)`；我此前提议的「字母+数字」(`D1`/`D0`/`F50`) **正式作废**。由此**确证** `TARGET_NUMBERS` 是不良品编号（`1`=NG=吹掉），原先的【推断】升级为【已确证】。设计文档 §9 重写、§5.1 目录树补 `arduino/`、§6.4.1 改口径、§12 表头 6→5 且 **Q3 关闭一半**（格式已定，剩「每帧发还是每颗发」+ `send_on_change_only: true` 会让连续两颗 NG 只吹第一颗）；本文件新增 §5.4.1、§2 改写、§3 其他段、模块表、§9 未验证段 |
| m03412 | 用户：「我需要确保每一张图片都要识别到，对于每一张图片都需要发出对应的处理信号」→ **Q5 由此裁定：不许丢帧，每帧必发一个字节**。改了 5 个文件：`app/workers.py`（队列不设上限、`submit` 不再丢最旧、异常也产出 `status="error"` 结果、`finally` 里发 `frame_processed`）；`infra/image_source.py`（`BaseSource` 加 `read_failed` + `frame_done`；`FolderSource` 改 single-shot 定时器、一帧在飞；`CameraSource` 改 `threading.Event` 等 ack、不再按 fps 闷头读；`cv2.imread` 失败改上报而不是跳过）；`app/controller.py`（接 `frame_processed` → `_ack_source()`；新增 `_on_read_failed`；删掉 `send_on_change_only` 分支，串口开着就每帧必发；新增 `frames_in`/`results_out`/`pending` 对账）；`ui/widgets/serial_panel.py`（删「仅变化时发送」勾选，换成一行说明）；`ui/main_window.py`（状态栏加「待处理 N」）。`config.yaml` 删 `serial.send_on_change_only`、改写 `poll_interval_ms` 注释 |
| — | 【已实测】`_verify_every_frame.py` 25 项全过：A 组 `test3` 12 张、`interval_ms=0`（最快节奏）→ `frames_in=12 / results_out=12 / 串口字节=12 / CSV 行=12 / 队列残留=0 / 最大积压=0`，且串口字节序列 `[1,1,1,1,1,0,1,0,1,0,1,0]` 与 CSV 的 `output_value` 逐条一致；B 组「1 好图 + 1 坏图」→ 2/2/2/2，坏图 `status=read_failed`、进了 CSV、也发了 `'0'`。UI 冒烟 `_verify_ui_smoke.py` 12 项全过（状态栏 `待处理 0`、喂一条结果后 `已处理 1 / 命中 1 / 待处理 0`、坏图 `frame=None` 进历史显示「无图」）。`compileall` 退出码 0；`test/run_app.py --check` 自检全部通过；离屏 GUI 起 14 秒无异常。**`CameraSource` 的新等待逻辑无硬件，未实测**。提交 **`8ed7733`** |
| m03646 | 用户一次回完四个设计问题：**「Q1：识别失败时串口发0；Q2每一帧只会出现一颗；Q4：最好是离线；Q6：COM口连接的时arduino uno r3」** → **设计文档 §12 至此无待决项**。落地：Q1 = 选项 (a)，**当前实现即正确不改代码**，缺陷 D1 关闭为「明示接受」（读不出的缺陷件会放行到下游）；Q2 = **一帧一颗**，单结果数据结构成立（未明确的一半：亮底暗字，仍按 `THRESH_BINARY_INV` 实现）；Q4 = 离线是**偏好非硬约束**，现状已满足，`config.yaml` 给 `PP-OCRv5_server_rec` 加「本地不存在、需联网」注释；Q6 = 板子 **Arduino Uno R3**，新增「接收端板子」表并记下 ⚠️ **DTR 自动复位会让打开串口后的前 1.5~2 s 字节被丢弃**（与 §6.4「每帧必发」冲突，待真机确认是否在 `SerialService.open()` 加静默期）。文档升 **v1.6**（§9 新增板子段、§10 用户定的表 +4 行、§12 表头改「已全部裁定」、§14 下一步重写）；本文件 §2 新增「设计问答 Q1–Q6 已全部裁定」表、§5.4.1 加板子表、§9/§10 重写 |
| m03767 | 用户：「结合arduino目录下的文件，arduino烧录后能够跑通，符合预期」→ **固件已烧录并验证通过**（`arduino/sketch_oct19a/sketch_oct19a.ino` 43 行：`'1'` 触发、`'0'` 关闭、100ms 自动收）。据此把 §5.4.1 的「烧录状态」改为 ✅，§9 未验证段、§10 下一步、模块表同步。**同时读固件发现一个隐式耦合**：`'0'` 不是空操作，而是 `digitalWrite(VALVE_PIN, LOW)` + `pulsing=false`，所以**帧间隔一旦 < `PULSE_MS=100`，后继那颗 G 的 `'0'` 会掐断上一颗 NG 的吹气**；现在单帧约 220ms 不会触发，但换快模型/少勾角度就会。解耦要么 Python 侧不发后继 `'0'`（破坏「每帧必发」），要么固件改成「不打断正在进行的脉冲」—— 属固件语义选择，待用户定。**仍未验证**：`PULSE_MS` 对实际喷气嘴是否合适、DTR 复位是否吞字节、Python 侧到真板子这一跳 |
| m03833 | 用户：「我运行run_app.py跑图之后，对于NG信号arduino会亮灯」→ **Python → 真板子 这一跳打通**：`SerialService` 打开 COM 口、每帧发一个字节、NG 帧固件拉高 `VALVE_PIN`+`LED_PIN`。至此「图像 → OCR → G/NG → 串口 → 板子输出」主链**全段实测**。§5.4.1 板子表新增「Python 侧已驱动成功」行、DTR 行改为「不影响整体流程、但第一颗是否被吞未单独验证」；§9 未验证段收缩为「气动阀是否真吹料 + GUI 其余按钮 + 摄像头」；§10 下一步改为「接气源 + 喷气嘴验证真正吹掉料」|
