# OCR 识别系统 —— 设计文档

| 项 | 值 |
|---|---|
| 日期 | 2026-10-15（初稿）／ **2026-10-16 修订（v1.2）** |
| 主题 | ocr_system：圆形标记数字识别 + 1/0 判定 |
| 状态 | 设计已定稿；**模型加载链路已端到端跑通**，但尚未灌过一帧真实图像（见 §11.4 / §14） |
| 文档用途 | 交给一个没参与过讨论的构建者，让他能据此排计划并动手，不必回头问人 |
| 代码位置 | `E:\Python Project\ocr_system` |
| 本次修订 | §6.1/§6.2 算法补注、**§6.4.1 新增 `G`/`NG`/`?` 显示规则**、§7 配置、§8 界面（含**新增** §8.1 角度面板规则 / §8.2 历史面板规则）、§9 串口、§10 决策记录（补 J7–J10）、§11 已知缺陷（两个阻塞项**均已解决**）、§12 待裁定问题（Q4 已改写）、§13 验收标准（+2 条）、§14 实现状态；**新增 §15 环境与依赖（已实测）** |

**阅读约定**：本文严格区分三类内容 ——
- **【用户定的】**：用户本人明确说过的，不可擅自推翻
- **【我的判断】**：我替用户做的决定，用户没否决但也没明确同意 —— 这些是**最该被质疑**的部分
- **【推断】**：我从代码/数据反推出来的，可能错

**v1.2 修订时的重要提醒**：本文初稿写作时（10-15 23:56）项目的真实状态与现在**不同**。
初稿把所有"未验证"都归因于一个**错误的**诊断（"模型目录被 OS 权限挡住"），
该诊断已被推翻（见 §11.1）。读 §11 时以本版为准。

---

## 1. 要解决的问题

一枚**圆形标记**（暗色药片状，直径约 200 像素级）上印着一个数字，取值范围 **1–48**。
它在工业**筛选机**上随物料高速通过摄像头。系统需要：

1. 从画面中**找到这枚圆形标记**（画面里可能有其他干扰）
2. **读出上面的数字**
3. 判断这个数字**是否属于一个预设的目标集合**，输出 **1（命中）或 0（未命中）**
4. 把这个 1/0 **通过串口发给下游**（Arduino）
5. 同时在**界面上显示**、在 **CSV 里留档**、在**历史面板里可回看**

### 为什么这件事不简单

标记在画面里**朝向任意** —— 可能转了 90°、180°，也可能斜着 30°。普通 OCR 直接读会失败。

`test/test_ocr2.py`（现成可跑的脚本，371 行）已经解决了这个问题，做法是：
**先裁出圆形区域，再把它按多个角度各转一遍，每个角度都送去识别，取最好的结果。**
本系统的核心任务就是把这个已验证的做法**工程化**：拆成可复用、可配置、带界面、带记录的结构。

> **【用户定的】** 重构必须**保持与 `test/test_ocr2.py` 一致的行为**。那两个脚本是算法行为的权威依据，不是参考。

---

## 2. 目标 / 非目标 / 反目标

### 目标

| # | 目标 | 出处 |
|---|---|---|
| G1 | 文件夹 / 摄像头两种图源可切换 | 【用户定的】 |
| G2 | 识别模型可在界面切换（多选一） | 【用户定的】 |
| G3 | 识别角度可在界面勾选（多选） | 【用户定的】 |
| G4 | 串口连 Arduino，发送判定结果 | 【用户定的】 |
| G5 | 历史记录面板，可回看 | 【用户定的】 |
| G6 | 单一配置文件 `config.yaml`，常量不硬编码 | 【用户定的】 |
| G7 | 行为与 `test/test_ocr2.py` 一致 | 【用户定的】 |

### 非目标（本次明确不做）

| # | 非目标 | 出处 |
|---|---|---|
| N1 | **速度指标**。118ms 或 209.6ms 都不是验收标准，不做性能优化 | 【用户定的】原话「你目前不用管速度」 |
| N2 | **Arduino 端的动作逻辑**（分拣、剔除、报警等），本系统只管把 1/0 发出去 | 【用户定的】 |
| N3 | **复杂的串口协议**：不做握手、不做应答、不做重传、不做 ACK | 【用户定的】+【我的判断】 |
| N4 | 模型训练 / 微调。只用现成 PaddleX 模型 | 【推断】 |
| N5 | 网络服务、多机协同、数据库 | 【推断】 |

### 反目标（技术上能跑，但仍然是失败）

**【推断，未与用户确认 —— 请重点核对】** 这个系统输出的是 1/0，下游据此分拣。
所以真正的失败不是"程序崩了"，而是：

- **A1 判定错了**：把该判 1 的判成 0（漏判），或反过来（误判）。这是最严重的失败，比崩溃更糟 —— 崩溃会被发现，错判会静默流出去。
- **A2 静默降级**：识别失败（`circle_not_found` / `no_number`）时，如果被当成"0 未命中"发出去，就等于**把"没看清"和"看清楚了但不是目标"混为一谈**。这两者在业务上很可能需要区分对待。**当前实现正是这样处理的 —— 见 §11 缺陷 D1。**
- **A3 用户不知道系统当前用的什么模型 / 什么角度**：界面上看不到，就会拿错误的配置跑一整批。

---

## 3. 约束

| 约束 | 说明 |
|---|---|
| 平台 | Windows |
| Python | 3.12（`pyproject.toml` 要求 `>=3.12`，实际 3.12.10） |
| **Qt 绑定** | **PyQt6 6.11.0**。【用户定的】—— 用户自己的 `pyproject.toml` 写死了 `pyqt6`。**不要换成 PySide6。** |
| **`core/` 必须零 Qt 依赖** | 【用户定的】用户给的目录结构里明确标注「★ 纯 Python，无 Qt 依赖」。`core/` 只允许依赖 Python 标准库 + numpy + cv2。 |
| 模型运行库 | PaddleX（`paddlex.create_model`），**不用 paddleocr** |
| 包管理 | **uv**。该 venv **没有 pip**（`No module named pip`），`python -m pip` 用不了 |
| 依赖声明位置 | **`pyproject.toml`**。`requirements.txt` 是**空文件**，不要信它 |
| 版本控制 | **没有** —— 项目不是 git 仓库。改动无法回滚，需谨慎 |
| 离线可用 | 模型必须已在本地缓存。**`PP-OCRv5_server_rec` 本地没有**，选中它需要联网下载 |

---

## 4. 一次运行长什么样

1. 用户双击启动 → 主窗口出现，**左侧空白、右侧一堆面板、状态栏显示"已处理 0 命中 0"**
2. 用户选模型（识别模型 + 方向模型）→ 点加载 → 状态栏/模型面板提示"加载识别模型 xxx…"，加载完变"模型已加载"
3. 用户选图源：文件夹（选路径、间隔、是否循环播放）或摄像头（选序号、FPS）→ 点开始
4. 画面开始在左侧显示。每来一帧，后台线程识别，结果叠加画在主图上（画框 + 数字 + 置信度），右侧结果显示面板刷新
5. 底部历史面板追加一条缩略图。点某条缩略图 → 主图区回看那一帧
6. 若有串口打开着，每次出结果就往下游发一个字节
7. 每帧结果追加写入 `logs/results.csv`
8. 关闭窗口 → 停止图源、停推理线程、关串口、关 CSV

> **【用户定的】** 用户此前提供过一张界面草图（六个面板 + 主图 + 历史条的 ASCII 布局）。当前实现与那张草图一致。

---

## 5. 架构

### 5.1 分层

```
main.py                 入口：设环境变量 → 读 config → 起 QApplication → 组装 → 跑
config.yaml             唯一配置文件

core/                   ★ 纯 Python 逻辑层，零 Qt 依赖
  models.py             RecognitionResult 数据类（帧结果的唯一载体）
  preprocess.py         CLAHE 增强 / 定位圆形 ROI / 多角度旋转 / 生成变体
  parsers.py            解析 PaddleX 的返回（格式多变，需兼容）
  engine.py             EngineManager：按模型名缓存模型实例，带线程锁
  recognizer.py         多角度识别主循环（角度遍历 + 方向分类 + 早退）
  decision.py           DecisionMaker：数字 → 1/0
  pipeline.py           OcrPipeline：单帧端到端串联

infra/                  基础设施（允许用 Qt；见 §11 D2）
  image_source.py       FolderSource / CameraSource
  serial_service.py     极简串口：开 / 关 / 发一个字节
  csv_logger.py         CSV 留档

app/                    编排层
  controller.py         AppController：持有 core 对象、串口、CSV、线程；发 Qt 信号给 UI
  workers.py            EngineLoadWorker / InferenceWorker（QThread）

ui/                     界面层
  main_window.py        主窗口，组装七个面板
  overlay.py            在主图上画框 + 叠加结果
  widgets/              七个面板部件（见 §8）

logs/                   app.log / results.csv
resources/icons/        当前为空
test/                   test_ocr2.py / test_rename.py ← 行为权威依据，不要改
```

**分层规则**：`core` 不知道 Qt 存在，也不知道 UI 存在。`app` 负责把 `core` 接到 Qt 上。`ui` 只通过 `controller` 的信号槽跟外部打交道，不直接碰 `core`。

### 5.2 数据流

```
图源线程 ──frame_ready──> AppController._on_frame
                              ├── frame_ready 信号 ──> ImageView（显示原图）
                              └── infer_worker.submit(frame, name)

InferenceWorker 线程 ──> OcrPipeline.run_on_image ──> RecognitionResult
                              └── result_ready ──> AppController._on_result
                                     ├── result_ready 信号 ──> MainWindow._on_result
                                     │      ├── ImageView.set_result（画框叠加）
                                     │      ├── ResultPanel.update_result
                                     │      └── HistoryPanel.add_result
                                     ├── CsvLogger.write
                                     └── 串口 send_value(output_value)
```

### 5.3 线程模型

| 线程 | 干什么 | 注意 |
|---|---|---|
| 主线程（Qt） | 所有 UI 绘制与信号槽 | 绝不在此做模型推理 |
| `InferenceWorker`（1 个，随 controller 启动） | 串行跑 `OcrPipeline` | 队列 `maxsize=1`，**满了丢最旧帧**，保证实时性 |
| `EngineLoadWorker`（每次点加载新建一个） | 加载模型（耗时数秒） | 防止加载时界面卡死 |
| 图源线程 | `CameraSource` 是 `QThread`；`FolderSource` 用 `QTimer` | 见 §11 D2 |

---

## 6. 核心算法（必须与 `test/test_ocr2.py` 一致）

> 这一节是本系统的技术核心。**改动前先跑 `test/test_ocr2.py` 对照。**

### 6.1 定位圆形 ROI

```
gray → cv2.threshold(gray, 127, 255, THRESH_BINARY_INV)
     → 5×5 全 1 核 MORPH_OPEN，再 MORPH_CLOSE      （去噪 + 补洞）
     → findContours(RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
     → 取 contourArea 最大的那个
     → cv2.minEnclosingCircle → (cx, cy, r) 取整
     → 若 r < min_radius(20) 或 r > max_radius(200) → 失败
     → 以 (cx,cy) 为中心取 roi_size(116) 见方，坐标夹到图像边界
     → 若裁剪后宽或高 < 116 → 失败
```

**关键前提（易踩坑）**：用 `THRESH_BINARY_INV`，意味着**标记必须是暗的、背景是亮的**。
若是白标记黑背景，最大轮廓会变成整幅背景，半径必然超过 200 而直接失败。
→ 测试时用的合成图必须是**亮底暗圆**。

### 6.2 生成多角度变体

```
按 |angle| 升序排列                       （先试接近正立的，命中率高）
angle == 0  → 直接用原 ROI，不旋转不缩放
否则        → getRotationMatrix2D((w/2, h/2), angle, scale)
              new_w = int(scale * (h*|sin| + w*|cos|))     ← 重算画布，防止转完被裁掉
              new_h = int(scale * (w*|sin| + h*|cos|))
              M[0,2] += new_w/2 - cx
              M[1,2] += new_h/2 - cy                        ← 重新居中
              warpAffine(INTER_LINEAR, BORDER_REPLICATE)
最后：灰度图 → cvtColor(GRAY2BGR)          （识别模型要 3 通道）
```

### 6.3 识别主循环

```
对每个变体（按 |angle| 升序）：
    ① ori.predict([img]) → parse_ori_output
         若返回 1（判定为倒置）→ cv2.rotate(img, ROTATE_180)   ← 先纠正向再识别
    ② rec.predict([fixed]) → parse_rec_output → [(text, score)]
    ③ 过滤：
         score < conf_threshold(0.6)              → 丢弃
         text 里剔除非数字字符后为空              → 丢弃
         drop_zero 且结果 == "0"                  → 丢弃
    ④ 记入候选 (cleaned, score, angle)
    ⑤ 早退：仅当 angle == 0
            且 score >= early_exit_conf(0.98)
            且数字 ∈ [valid_min, valid_max]      → 立即返回

全部候选按 score 降序排列
返回第一个数字 ∈ [valid_min, valid_max] 的候选
都不满足 → None
```

**注意**：早退条件**绑死了 `angle == 0`**。非 0° 角度即使置信度 0.99 也不会早退 —— 这是刻意的（0° 是正向，可信度最高）。

### 6.4 判定 1/0

```
status != "ok"           → 0
number 为空 或 == "0"    → 0
int(number) 不在 [1,48]  → 0
number ∈ {12,19,20,25,37,41,43}  → 1
否则                     → 0
```

→ `output_value == 1` 严格等价于 `hit == True`。

#### 6.4.1 界面显示：`1/0` **不**直接露给操作员，显示成 `NG` / `G`（【用户定的】，m01391）

用户原话：「0要对应显示G，1要对应显示NG」。所以映射是：

| 情形 | `output_value` | 界面文字 | 配色 |
|---|---|---|---|
| 数字**命中**目标集合（`hit == True`） | `1` | **`NG`** | 红 `#e74c3c` |
| 数字**不在**目标集合 | `0` | **`G`** | 绿 `#2ecc71` |
| **识别失败**（`circle_not_found` / `no_number` / `read_failed` / `error`） | `0` | **`?`** | 橙 `#e67e22` |

**【推断，值得复核】**由此反推业务语义：`TARGET_NUMBERS`（`{12,19,20,25,37,41,43}`）
是**不良品编号** —— 打上这些数字的零件判 `NG`，其余判 `G`。
这与「筛选机把目标数字挑出来」的直觉表述相反，但和用户「0→G、1→NG」的指令一致。
若实际是反的（目标数字才是良品），只需把 `output_text` 里的 `NG`/`G` 两个字符串对调。

★ **第三行是必须单独处理的**：识别失败时 `output_value` 也是 `0`（见 D1），
若照搬映射就会显示成绿色的 `G` —— 那等于把「没看清」误报成良品，
直接违反 §2 的反目标 A2。所以失败档一律显示 `?`，颜色也与 G / NG 都不同。

**实现位置（唯一真源）**：`core/models.py` 的 `RecognitionResult.output_text` 只读 property。
界面四处都取自它，保证不会各写一份：

- `ui/widgets/result_panel.py` —— 大方框文字 + 底色
- `ui/widgets/history_panel.py` —— `数字 → G/NG` 文字 + 卡片边框色
- `ui/overlay.py` —— 画在图像上的大字与 ROI 框颜色
- `ui/main_window.py` —— 状态栏 `当前 xxx → G/NG`

⚠️ **只改显示，不改数据**：串口发送（`app/controller.py`）和 CSV 落盘（`infra/csv_logger.py`）
仍然使用原始的整数 `output_value`（`b'1'` / `b'0'`、CSV 里是 `1` / `0`）。
Arduino 侧与历史数据格式**不受本次改动影响**。

### 6.5 参数总表（全部来自 `test/test_ocr2.py`，已调优，**不要随手改**）

| 参数 | 值 | 含义 |
|---|---|---|
| `target.numbers` | `{12,19,20,25,37,41,43}` | 目标集合，命中即 1 |
| `valid_min` / `valid_max` | 1 / 48 | 有效数字范围 |
| `conf_threshold` | 0.6 | 置信度下限 |
| `early_exit_conf` | 0.98 | 0° 早退阈值 |
| `roi_size` | 116 | ROI 边长（像素） |
| `scale` | 1.0 | 旋转时的缩放 |
| `angles` | `-90,-60,-45,-30,0,30,45,60,90,180` | 10 个角度 |
| `clahe_clip` / `clahe_grid` | 2.0 / (8,8) | CLAHE 增强参数 |
| `min_radius` / `max_radius` | 20 / 200 | 圆半径守卫 |
| `drop_zero` | true | 丢弃 "0" |
| 环境变量 | `OMP_NUM_THREADS=8`, `MKL_NUM_THREADS=8` | **必须在 import cv2 之前设** |
| cv2 线程 | `cv2.setNumThreads(1)` | 避免与 numpy 抢线程 |

---

## 7. 配置 `config.yaml`

单一配置文件。**代码里的默认值必须与它一致，不允许两处各写一份。**

```yaml
app:        log_dir: "./logs"   csv_output: "./logs/results.csv"   save_csv: true
target:     numbers: [...]      valid_min: 1   valid_max: 48
models:     rec_options: [...]  ori_options: [...]  default_rec: ...  default_ori: ...
recognizer: conf_threshold: 0.6   early_exit_conf: 0.98
            angles: [...]   drop_zero: true
preprocess: roi_size: 116   scale: 1.0   clahe_clip: 2.0   clahe_grid: [8,8]
            min_radius: 20   max_radius: 200
source:     type/folder_path/camera_index/fps/poll_interval_ms/loop
serial:     baudrate: 115200   last_port: "COM3"   send_on_change_only: false
```

**【我的判断】两个配置区的定位**：
- `models.rec_options` / `ori_options` 是**候选清单**（给下拉框用），`default_rec` / `default_ori` 是**初始选中项**
- `source:` 段**意图上**应作为界面初值，但当前实现里界面硬编码了 15fps / 300ms / 循环开 —— 见 §11 D3
- `serial.last_port` / `baudrate` 意图上应作为串口面板初值，当前未接线 —— 见 §11 D3

**⚠️ 已知冗余**：`valid_min`/`valid_max` 同时出现在 `target:` 段和 `recognizer.py` 的默认值里，两处会漂移。见 §11 D4。

---

## 8. 界面

主窗口 1400×900。布局：

```
┌─────────────────────────────────┬──────────────────┐
│                                 │  模型面板         │
│                                 │  输入源面板       │
│        主图像区（Image）          │  角度面板         │
│   画框 + 数字 + 置信度叠加        │  结果显示面板     │
│        最小 640×480              │  串口面板         │
│                                 │  (弹簧)           │
├─────────────────────────────────┴──────────────────┤
│  历史缩略图条（横向，最多 200 条）                    │
├────────────────────────────────────────────────────┤
│  状态栏：已处理 N | 命中 M | 平均 X.Xms | 当前 ...   │
└────────────────────────────────────────────────────┘
左右分割比例 3:1
```

**v1.2 修订：上面这张图仍成立，但两处实现细节要补上（都已实测）**

1. **两个方向都可拖**（`ui/main_window.py`）：
   - 横向 `QSplitter` 分主图区与右列 —— 3:1。
   - 纵向 `QSplitter`（`v_splitter`）分「上半区」与「历史区」—— 初值 `setSizes([640, 230])`。
     历史区**可以一直往下拖**，下限由 `HistoryPanel.MIN_VIEW_H = 56` 决定，
     实测最小 113px；再往下拖不动（`setCollapsible(1, False)`，防止「清除历史」按钮被拖没）。
   - ⚠️ 右侧那列面板的总最小高度（实测 **877px**）**超过**它拿到的默认高度（约 679px）。
     所以右列**外面套了 `QScrollArea`**，它自己出竖向滚动条 —— 这是**常态，不是 bug**。
     陷阱：`QScrollArea` 自己算的最小宽度**不含**内部控件的要求，必须显式设成
     `right.minimumSizeHint().width() + 竖向滚动条宽度`，否则外侧会把右列压窄到内容以下、把控件裁掉。
2. **历史区高度与缩略图尺寸是两件事**（踩过两次，见 §10 决策记录）：
   区域高度可调，**缩略图尺寸恒定 120×120**。

| 面板 | 类 | 用户能做什么 | 发/收的信号 |
|---|---|---|---|
| 主图区 | `ImageView(QLabel)` | 看画面与结果；点历史项可回看 | 收 `set_frame` / `set_result` |
| 模型面板 | `ModelPanel` | 选识别模型 + 方向模型；点加载 | 发 `load_requested(rec, ori)`；收 `set_progress(msg)`（加载中）/ `set_loaded(ok, msg)`（终态） |
| 输入源面板 | `SourcePanel` | 选文件夹 / **单图** / 摄像头；选路径、FPS、间隔、循环；开始/停止 | 发 `start_requested(dict)` / `stop_requested()`；收 `set_running_false()` |
| 角度面板 | `AnglePanel` | 勾选参与识别的角度（0°~180° 每 10° 一格）+「负号」开关 + 全选/仅 0°/反选/默认 | 发 `angles_changed(list)` |
| 结果显示面板 | `ResultPanel` | 只读：数字、置信度、角度、状态；**大方框显示 `G` / `NG` / `?`**（§6.4.1），悬停可见原始 `output_value` | 收 `update_result(res)` |
| 串口面板 | `SerialPanel` | 刷新端口、打开/关闭、勾选"仅变化时发送"；看收发统计 | 发 `open_requested(port,baud)` / `close_requested()` / `refresh_requested()`；收 `set_ports` / `set_connected` / `update_stats` |
| 历史面板 | `HistoryPanel` | 看缩略图列表（横/竖滚轴按需出现）；点某条回看；**「清除历史」按钮** | 发 `item_clicked(res)` / `cleared()`；收 `add_result(res)`；每条卡片显示 `数字 → G/NG/?`，边框色同 §6.4.1 |

**⚠️ 注意（v1.2 仍未修）**：输入源面板有**三个**单选（文件夹 / 单图 / 摄像头），但 `AppController.start_source` 只处理 `camera` 和 `else`（都当文件夹走）。

**【我的判断】「单图」应实现为真实的第三种模式**：载入单张图 → 跑一次 → 自动停止；结果同样写 CSV、进历史面板、参与统计。语义以「跑一次即停」为准，不循环。见 §11 D5。

### 8.1 角度面板的规则（【用户定的】，两轮改出来的）

| 规则 | 来源 |
|---|---|
| 可选角度是 **0°~180° 每 10° 一格，共 19 格**（列表里不出现负数） | 用户：「只显示0-180，步长是10」 |
| **0° 和 180° 独立成一行**，永不受「负号」影响 | 用户：「0度和180度独立出来不受负号影响，因为-0度-180度没意义」 |
| 其余 **10°~170° 共 17 格**由「负号」复选框控制：勾上则每个勾选的 θ 同时尝试 −θ | 用户：「添加负号勾选」 |
| `selected_angles()` 把两组合并后送给 `Recognizer`；因为旋转组里没有 0/180，展开 `−θ` **永不撞车**，早期版本里的 `if a != 0` / `discard(-180)` 特例已全部删掉 | 【我的判断】 |
| 旧配置里不在 10° 网格上的角度（如 −45/45）启动时被丢弃并打印提示 | 【我的判断】，避免静默吞掉 |

### 8.2 历史面板的规则（【用户定的】）

| 规则 | 来源 |
|---|---|
| 历史区高度**可自由拖动**；拖矮时缩略图被裁切，靠**竖向滚轴**看全；记录多时横向滚轴按需出现 | 用户：「可以一直向下拉，然后有一个滚轴」 |
| **缩略图尺寸固定 120×120**（卡片 132×161），**不随历史区高度变化** | 用户：「图片框会因为我拉高历史记录区的高度而变化，我需要固定图片的大小」 |
| 缩略图按**等比缩放居中**贴进固定画布（不拉伸）→ 源图比例与画布不一致时会有黑边，这是**正确行为** | 【我的判断】 |
| 顶部一行有「共 N 条」计数 + **「清除历史」按钮**；清除时同时把状态栏统计归零 | 用户要按钮；统计归零是【我的判断】，理由：空历史配着"已处理 128"看着像 bug |
| 上限 `MAX_ITEMS = 200`，超出丢最旧 | 原有实现 |


---

## 9. 串口

### 「极简」的含义

`infra/serial_service.py` 的自我定位（原文注释）：

> 极简串口封装：只负责「打开 / 关闭 / 发送单个 0/1 字符」。不做协议、不做重连、不做策略。

参数：`bytesize=8, parity='N', stopbits=1, timeout=0.05, write_timeout=0.2`，默认 `115200`。

### 发送内容

```
value == 1  →  发送单字节 b"1"
否则         →  发送单字节 b"0"
```

### ★★ 这是全项目唯一没人拍板的决定 ★★

**【我的判断，且用户从未确认】** 发送**裸字节 `'1'` / `'0'`** 这个格式，用户从头到尾**没有明确同意过**。

而且有一个**矛盾**需要澄清：
- `test/test_ocr2.py` 里**完全没有串口代码**（已 grep 确认，无任何 `serial` 相关）—— 所以原脚本**没有**可继承的协议
- 讨论过程中我曾提议过「字母+数字」格式（如 `D1`/`D0` 表示判定、`F50` 表示特征值），但**实现里没有采用**，实现是裸字符

→ **构建者必须先跟用户确认这个格式**，再动任何串口相关代码。这是本文档最大的未决项。

### 触发时机

```
Controller._on_result:
    若串口已打开：
        若 未勾选"仅变化时发送"  或  output_value != 上次发送值：
            send_value(res.output_value)
```

即：**默认每帧都发**（`send_on_change_only: false`）。勾上则只在 1↔0 翻转时发。
不发送的情况：串口未打开 → 什么都不做，静默跳过。

**串口发送失败**（写超时/掉线）→ 在状态栏提示 3 秒，**不影响主流程**，不重试。

---

## 10. 决策记录

### 【用户定的】—— 这些是约束，不是建议

| 决定 | 内容 |
|---|---|
| Qt 绑定 | PyQt6（用户自己写进 `pyproject.toml:11`）|
| 分层 | `core/` 零 Qt 依赖（用户原始目录结构注释）|
| 配置 | 单一 `config.yaml`，常量不硬编码 |
| 行为基准 | 必须与 `test/test_ocr2.py` 一致 |
| 功能范围 | 多模型切换 / 多角度勾选 / 文件夹+摄像头 / 串口 / 历史面板 |
| 砍掉 Arduino | 「不用考虑 arduino」 |
| 砍掉速度 | 「你目前不用管速度」 |
| 修复优先级 | 「先修复一到四」（审计问题的前四项）|
| 角度网格 | 「只显示 0-180，步长是 10」+「0 度和 180 度独立出来不受负号影响」（见 §8.1）|
| 历史区 | 「可以一直向下拉，然后有一个滚轴」+「固定图片的大小」（见 §8.2）|
| 模型位置 | 「能不能将所有模型都放在项目目录内，然后直接读取」→ 15 个模型目录复制进 `models/`（见 §15.2）|
| **判定显示** | 「0要对应显示G，1要对应显示NG」（m01391）→ 界面显示 `G`/`NG`，串口与 CSV 仍是原始 `1`/`0`（见 §6.4.1）|

### 【我的判断】—— 用户没否决，但也没明确同意，**最该被质疑**

| # | 我的决定 | 理由 | 风险 |
|---|---|---|---|
| J1 | 串口发**裸字节** `'1'`/`'0'` | 最简、够用、符合"N3 不做协议" | **未经确认**，且与我先前提议的 `D1`/`F50` 格式不一致 |
| J2 | 推理队列 `maxsize=1`，满了**丢最旧帧** | 筛选机要实时，宁可丢帧不可积压 | 会漏检 —— 如果业务要求"每颗都要判"，这个策略是错的 |
| J3 | 识别失败（未找到圆/没识别出）**也发 0** | 简化下游逻辑 | **可能严重错误**，见反目标 A2。**已升级为待用户裁定（§12 Q1）** —— 这是全项目第二重要的未决项 |
| J4 | 历史缩略图存**整帧**而非缩略图 | 实现简单 | 200 帧常驻内存，见 D6 |
| J5 | 模型加载放在独立线程 | 加载要数秒，不能卡 UI | 加载中用户可能误点开始 |
| J6 | `rec_options` 是候选清单，`default_rec` 是初值 | 下拉框语义 | 无 |
| J7 | 用 `PADDLE_PDX_CACHE_HOME` 把模型根目录**指到项目内的 `models/`**，而不是改 `EngineManager` 去传 `model_dir=` | 只改两行、`EngineManager` 完全不用动，且保留 PaddleX「缺模型自动下载」的能力；`model_dir=` 那条路要为每个模型改代码且丢掉自动下载 | **副作用：设了这个变量后 `~/.paddlex` 不再被读取**；`models/`（477MB）已在 `.gitignore` 里 |
| J8 | 模型加载的**进度**和**终态**拆成两个信号（`engine_progress(str)` / `engine_status(bool,str)`） | 原先两者共用一个带 bool 的信号，进度被当成 `ok=False` → 界面先闪「加载失败」 | 无（已修，见 §11.3） |
| J9 | 历史区高度与缩略图尺寸**解耦**；缩略图固定 120×120 | 用户两句要求看似矛盾，实际是「区域可调」+「图片固定」两件事 | 历史区拖很矮时缩略图被裁切，需要竖向滚轴（已按需开启）|
| J10 | 「清除历史」时**同时把状态栏统计归零** | 空历史配着"已处理 128"看着像 bug | 串口面板自己的收发计数**不动**（那是设备侧统计，不是本次会话的）|
| J11 | **识别失败时显示 `?`，而不是按 `0→G` 映射显示成 `G`** | 失败时 `output_value` 也是 `0`（D1），显示成绿色 `G` 等于把「没看清」误报成良品，违反反目标 A2 | 严格说超出了用户原话（用户只给了 0/1 两条映射）。若用户要求「失败也显示 G」，改 `core/models.py` 的 `output_text` 一行即可 —— **但这不建议**，见 §6.4.1 |
| J12 | `G`/`NG` 的**配色**定为「G 绿 / NG 红 / ? 橙」 | G/NG 是合格判定，制造业 HMI 通行的绿=合格、红=不合格 | 这**推翻了原配色**（原先 `output_value==1` 是绿色）。若用户只想改文字不想动颜色，删掉 `ResultPanel._STYLES` 里的色值即可 |


---

## 11. 已知缺陷与待定项

> 这些是**当前代码里真实存在**的问题。构建者排计划时应把它们纳入。

| # | 位置 | 问题 | 严重度 |
|---|---|---|---|
| **D1** | `app/controller.py:114-120` + `core/decision.py:24` | **识别失败也发 0**。`circle_not_found` / `no_number` 时 `output_value = 0`，串口照样发 `'0'`。等于把"没看清"和"看清了但不是目标"混为一谈。 | **高** —— 见反目标 A2，需用户裁决 |
| ~~D2~~ | `infra/image_source.py:3` | 引入了 `QTimer`/`QThread` → `infra/` 不是纯 Python 层。 | ✅ **已裁定：接受**。用户的「零 Qt 依赖」原话只标注在 `core/` 上（「core/ ★ 纯 Python，无 Qt 依赖」），`infra/` 从未被要求纯 Python，且 `core/` 确实干净。仅记录在案，**不重构**。 |
| **D3** | `config.yaml:35-45` | `source:` 段和 `serial.last_port`/`baudrate` **根本没被读取**；界面里硬编码了 15fps / 300ms / 循环开。 | 中 |
| **D4** | `config.yaml:8-9` 与 `core/recognizer.py:16-17` | `valid_min`/`valid_max` **两处重复定义**，会漂移。 | 中 |
| **D5** | `ui/widgets/source_panel.py:94` + `app/controller.py:80-85` | 界面有"单图"选项，但 controller 只认 `camera` 和 `else`（都走文件夹）。选单图会拿到文件路径当作文件夹。 | 中 —— **【我的判断】应把「单图」实现为真实的第三种模式**（载入单张图 → 处理一次 → 停止；结果照常进 CSV/历史）。理由：界面已提供该选项，删掉它是破坏功能，实现它是安全默认。 |
| **D6** | `core/models.py:19` + `ui/widgets/history_panel.py:66` | `frame` 存**整帧** + `MAX_ITEMS = 200` → 最多 200 张整帧常驻内存。 | 中 |
| **D7** | `infra/csv_logger.py:16` | `open(self.path, "w", ...)` —— **每次启动清空 `logs/results.csv`**，历史留档丢失。 | 中 |
| **D8** | `main.py:32` + `ui/main_window.py:150` | **两处**都会调 `controller.shutdown()` → 关闭时执行两次。 | 低 |
| **D9** | `core/pipeline.py:45` | 调 `decider.decide(num)` 未传 `status`，而 `decision.py:23` 有这个参数（默认 `"ok"`）→ 参数形同虚设。 | 低 |
| **D10** | `resources/icons/` | 空目录，无图标资源。 | 低 |

> **v1.2 状态**：D2 已裁定「接受」（不重构）。D1、D3–D10 **都还没修** ——
> 它们不影响启动与模型加载，属于待用户排序的工作。

### 11.1 ✅ 阻塞项 1：曾被判为「模型目录被 Windows 文件权限挡住」—— **已推翻，根本不是权限问题**

**结论：目录权限从头到尾都是好的。当时看到的 `PermissionError [WinError 5] 拒绝访问` 是 DSH 沙箱在挡「工作区之外」的路径。**

判据（可复用）：**把同一个读操作加 `danger-full-access` 再跑一次** ——
能读 = 沙箱；仍不能读 = 才是 OS ACL。这次去沙箱后 15 个目录**全部可读**，
`PP-OCRv6_small_rec\inference.yml` 也在，`.paddlex` 与 `official_models` 均可写。

为什么会误判成 OS ACL：

- `icacls` 在子目录上报 `Access is denied. Successfully processed 0 files; Failed processing 1 files`
- 但 `icacls` 在父目录上能看到 `DESKTOP-3HNC2MT\14734:(I)(OI)(CI)(F)` —— 当前身份在父目录上有**继承的完全控制**
- 父目录 ACL 里还有一个 `CodexSandboxUsers:(I)(OI)(CI)(RX)` —— **那是机器上早就存在的本地组**
  （注释 `Codex sandbox internal group (managed)`，成员 `CodexSandboxOffline`/`CodexSandboxOnline`），
  不是本项目建的，也不是失败原因
- 线索：`dir /a` 报 `File Not Found` 而 `icacls` 报 Access is denied，自相矛盾 ——
  矛盾本身就是「不是 ACL 层在拦」的信号

**对构建者的意义：不需要修任何权限，也不需要 `diagnose-windows-sandbox-acl`。**
（后来用户在普通会话里自己跑通了，进一步印证。）

### 11.2 ✅ 阻塞项 2：`create_model` 缺依赖 —— **已定位并修复（这是真实根因）**

三个独立的问题叠在一起，全部已修复并实测通过。

| # | 现象 | 真根因 | 修法 |
|---|---|---|---|
| ① | `DependencyError: PDFReaderBackend ... pypdfium2 / opencv-contrib-python` | paddlex **只在 extras 里**声明这几个包（`extra == "cv"` / `"ocr-core"` / `"ocr"` / `"base"` …），`dependencies` 里裸写 `"paddlex"` **必然缺**；而 `ImageBatchSampler.__init__` **无条件**构造 `PDFReader`，所以任何 `create_model()` 都会踩到，**与是否处理 PDF 无关** | 显式装 `opencv-contrib-python` + `pypdfium2` |
| ② | `ClassNotFoundException: PP-OCRv6_small_rec is not registered on BasePredictor` | **paddlex 版本过旧**：3.4.3 的注册表里根本没有 `PP-OCRv6_*`（只有 v5 及更早）；`configs/modules/text_recognition/PP-OCRv6_small_rec.yaml` 到 3.7.2 才有 | `uv pip install 'paddlex==3.7.2'` |
| ③ | 升到 3.7.2 后仍失败：`TextRecRunnerPredictor ... python-bidi` | 同一个 extras 问题，`python-bidi` 也在 extras 里 | 装 `python-bidi==0.6.11` |

**为什么不用 paddlex 的 extras（如 `paddlex[ocr]`）**：extras 把 `opencv-contrib-python` 钉死在 `==4.10.0.84`（旧版），
而项目已装的是 `opencv-python 5.0.0.93`，两个发行版会争抢同一个 `cv2/` 目录。
所以**显式列依赖、保留 contrib 5.0.0.93**（它是 `opencv-python` 的超集），并卸掉 `opencv-python`。

**版本约束（paddlex 3.7.2 的 METADATA 原文）**：`numpy<2.4,>=1.24`。
→ 所以 `pyproject.toml` 原先写的 `numpy>=2.5.4` 是**不可能满足**的约束（uv 会解成 2.3.5）。

### 11.3 顺手修掉的两个「诊断障碍」（**这才是当初看不懂报错的原因**）

| 位置 | 问题 | 修法 |
|---|---|---|
| `ui/widgets/model_panel.py` | `setText(f"● 加载失败: {msg[:30]}")` 把真实异常**截断到 30 字**，界面永远看不到根因 | 取最后一行、放宽到 60 字，完整信息放 `setToolTip` |
| `app/workers.py` | `except Exception as e: self.done.emit(False, str(e))` 只给一行字符串，**没有堆栈** | 加 `traceback.print_exc()` |

另外还有一个**独立的界面缺陷**（用户报「先显示加载失败，然后才显示已加载」）：
进度与终态共用一个带 bool 的信号 `engine_status(bool, str)`，进度被当成 `ok=False`，
于是每一条「正在加载 …」都被渲染成红色的「● 加载失败: 正在加载 …」。
修法见 §10 J8：拆成 `engine_progress(str)` / `engine_status(bool, str)` 两个信号，
并让加载中**禁用**「加载」按钮（原先 `set_loaded()` 无条件重新启用，导致加载中按钮已可点）。

### 11.4 尚未验证的功能

模型加载链路**已实测跑通**：
```
AppController.load_models('PP-OCRv6_small_rec', 'PP-LCNet_x1_0_textline_ori')
  → engine_status: ok=True  msg=模型已加载
```

仍未真正执行过的（**因为还没灌过一帧真实图像**）：

- `EngineManager` 的缓存是否真的只加载一次
- `Recognizer.recognize` 的角度循环、方向分类转 180°、早退逻辑
- `DecisionMaker.decide` 的判定
- `OcrPipeline.run_on_image` 端到端
- 所有 `infra/` 的串口、图源、CSV 实际读写
- 全部 GUI 交互（只点过「加载模型」按钮）

**已验证通过的**：全项目语法编译、21 个模块 import、`find_roi` 在真实样张上 11/11 找到圆、
`build_variants` 六角度尺寸正确、`AppController + MainWindow` 能用真配置构造出来、
角度面板与历史面板的离屏交互验收（见 §8.1 / §8.2）。

---

## 12. 留给构建者的

以下**故意不规定**，由构建者按需决定：

1. **`engine.py` 的缓存策略细节**：当前是"按模型名永久缓存，永不释放"。多个大模型同时驻留会吃内存 —— 是否需要 LRU 或上限，由构建者判断。
2. **推理队列的丢弃策略**（J2）：当前丢最旧帧。若业务要求不漏检，需改成阻塞或全量处理。
3. **历史面板的存储形式**（D6）：改成缩略图还是限制数量，由构建者定。
4. **`parsers.py` 的健壮性**：PaddleX 返回格式可能随版本变化，当前的兼容写法覆盖了 `dict` / `list` / 对象属性三种，是否需要更强校验由构建者定。
5. **日志**：`logs/app.log` 当前是空的，`app.log_dir` 配了但基本没用起来。日志策略由构建者定。
6. **错误处理粒度**：当前 `pipeline` 用一个大 `try/except` 兜住所有异常并记 `status="error"`。是否需要细分由构建者定。
7. **图标资源**：`resources/icons/` 是空的。
8. **打包分发**：未讨论。是否要做成 exe 由构建者/用户定。

### ★ 待用户裁定（这 6 个不定，设计就没定稿）

这些问题的答案会**改变要构建什么**，所以不能由构建者自行决定。按重要性排序：

| # | 问题 | 为什么它挡路 |
|---|---|---|
| **Q1** | **识别失败时（没找到圆 / 没识别出数字），串口该发什么？** (a) 照旧发 `0`（当前实现）(b) 什么都不发 (c) 发一个**可区分的第三态** | 选 (c) 的话，要贯穿改 `status` → `decide()` → 串口字节 → CSV 字段 → 界面计数器 → 历史面板一整条链，是结构性改动。见 J3 / 反目标 A2 |
| **Q2** | **一帧里会不会同时出现多颗标记？** 相机是等**硬件触发**还是自由跑？`project_0\data\test3` 那 11 张是**真实相机帧**吗？标记有没有可能**亮底暗字**（当前算法只认暗底亮字，见 §6.1）？ | 多颗 → 数据结构要从"一个结果"变成"一串结果"；亮底暗字 → `THRESH_BINARY_INV` 要自适应。都能翻掉现在的核心设计 |
| **Q3** | **串口到底发什么字节？** 当前实现是裸 `b'1'` / `b'0'`。每**帧**发一次还是每**颗**发一次？ | 这是全项目唯一没人拍板的决定（见 §9）。若将来要同时发频率，裸单字节表达不了 |
| **Q4** | **离线是硬约束吗？允许我继续加依赖吗？**（原「环境权限」问题**已作废** —— 那不是权限问题，见 §11 阻塞项 1） | 模型已全部本地化、依赖已固化，当前**可完全离线运行**。若「离线」是硬约束，构建者就不能换模型或加包 —— 而 `config.yaml` 里列的 `PP-OCRv5_server_rec` 本地并不存在，选它会联网下载 |
| **Q5** | **必须每颗都判，还是允许丢帧？** 当前推理队列满了丢最旧帧 | 若"每颗都要判"，J2 的实时优先策略直接是错的 |
| **Q6** | **有硬件可以验吗？** 相机接上了吗？COM 口上真有设备吗？**这台机器就是最终部署机吗**？ | 决定"跑通"的定义是仿真验证还是真机验证 |

**已经由本次检查自行解决、不需要用户回答的**：

- Q7「单图算不算真实第三种模式」→ 已判为**是**，见 D5 / §8。
- Q8「`infra/` 的 Qt 不纯要不要重构」→ 已判为**不重构**，见 D2（约束原话只加在 `core/` 上）。

---

## 13. 验收标准

【推断，需用户确认】系统算完成，当且仅当：

1. **算法等价**：同一批图，本系统输出的数字/置信度/角度与 `test/test_ocr2.py` **逐条一致**
   （已知 demo 在 `E:\Python Project\project_0\data\test3` 上跑 11 张的结果是：ok 10 条、no_number 1 条，
   命中 6 / 未命中 5，其中 6 条是在非 0° 角度上识别成功的，平均耗时 209.6ms）
2. 三种图源都能跑，能正常显示与停止
3. 模型切换后能加载并生效；角度勾选立即生效
4. 串口能列端口、开关、发送
5. `logs/results.csv` 每帧有记录，**且不因重启而清空**（修完 D7 之后）
6. 历史面板能回看，且内存不无限增长
7. 关窗时线程、串口、文件都被干净释放（且只释放一次）
8. **角度面板**：0°/180° 独立、不受「负号」影响；勾选角度按 §8.1 的规则展开；改勾选立即生效
9. **历史区**：区域高度可自由拖动（最小 113px），内容超出时出现**竖向**滚动条；
   缩略图恒为 120×120，**不随区域高度变化**

---

## 14. 当前实现状态

| 部分 | 状态 |
|---|---|
| 目录骨架（7 目录 / 31 文件） | ✅ 完成 |
| **环境与依赖** | ✅ 完成（见 §15）—— 模型**实测可加载** |
| `core/` 七个模块 | ✅ 代码完整；`preprocess.find_roi`/`build_variants` 已用真实样张实测，其余未跑过 |
| `infra/` 三个模块 | ✅ 代码完整，未跑过 |
| `app/` 两个模块 | ✅ 代码完整；`EngineLoadWorker` 加载链路**实测通过** |
| `ui/` 主窗口 + 叠层 + 七个面板 | ✅ 代码完整；加载模型链路实测通过，角度面板 / 历史面板离屏验收通过 |
| 配置 / 入口 | ✅ 完成 |
| 模型本地化（`models/official_models/`） | ✅ 完成（见 §15） |
| **端到端跑通（灌一帧真实图像）** | ❌ **未达成** |
| 打包 / 图标 | ❌ 未做 |

**下一步的唯一优先事项**：灌一帧真实图像跑通单帧端到端，才能验证 §11.4 那一整列「尚未验证」。

---

## 15. 环境与依赖（已实测）

**解释器（必须用这个）**：`E:\Python Project\ocr_system\.venv\Scripts\python.exe`
（Python 3.12.10，uv 管理，base `E:\Python312`）。系统默认的 `E:\Python313\python.exe` **不带**这些依赖。

**已装版本**：paddlepaddle 3.3.1、**paddlex 3.7.2**、numpy **2.3.5**（不是 2.5.4，原因见 §11 阻塞项 2 的版本约束）、
opencv-contrib-python 5.0.0.93、PyQt6 6.11.0、pyserial 3.5、PyYAML 6.0.2、pandas 3.0.6、Pillow 12.3.0、
pypdfium2 5.14.0、python-bidi 0.6.11。
**paddleocr 没装**（不需要，我们直接调 paddlex）。**venv 里没有 pip**（uv 建的），装包一律用 `uv pip install`。

**`pyproject.toml` 的依赖（每行带原因，改动前先读注释）**：

```toml
"numpy>=2.3.5",                    # 不能写 >=2.5.4：paddlex 3.7.2 要求 numpy<2.4
"opencv-contrib-python>=5.0.0.93", # 只留 contrib（opencv-python 的超集，避免两个发行版争 cv2/）
"paddlepaddle>=3.3.1",
"paddlex>=3.7.2",                  # 3.4.3 没有注册 PP-OCRv6_*
"pypdfium2>=5.14.0",
"python-bidi>=0.6.11",
"pyqt6>=6.11.0",
"pyserial>=3.5",
```

**模型已全部本地化到项目内**：`E:\Python Project\ocr_system\models\official_models\`（15 个目录，477.1 MB）。

机制：`paddlex\utils\cache.py:28-29` 的
`CACHE_DIR = os.environ.get("PADDLE_PDX_CACHE_HOME", DEFAULT_CACHE_DIR)` —— **在 import 时求值**，
所以 `main.py` 与 `test/run_app.py` 都在**任何 paddlex import 之前**执行
`os.environ.setdefault("PADDLE_PDX_CACHE_HOME", <项目根>/"models")`。
**副作用：设了它之后 `~/.paddlex` 不再被读取。** `models/` 已加入 `.gitignore`。

**本地实际有缓存的模型**：识别 `PP-OCRv6_small_rec`（20.5 MB）、`PP-OCRv6_medium_rec`（73.3 MB）；
方向 `PP-LCNet_x1_0_textline_ori`（6.5 MB）。
⚠️ `config.yaml` 的 `models.rec_options` 里还列着 `PP-OCRv5_server_rec`，**本地没有** —— 选它需要联网下载。

**已知环境限制（只影响开发时的 agent 会话，不影响产品本身）**：

- DSH 沙箱读不到工作区之外的 `C:\Users\14734\.paddlex\`（详见 §11 阻塞项 1）；
  `.venv` 在受限模式下只读，所以任何 `uv pip install` 都需要一次 `danger-full-access`。
- uv 默认缓存 `C:\Users\14734\AppData\Local\uv\cache` 在沙箱外 → 需设 `UV_CACHE_DIR` 指向工作区内。

**一键启动 / 自检**：`E:\Python Project\ocr_system\test\run_app.py`
（自动切到 venv 解释器、切到项目根、注入 `sys.path`、设 `PADDLE_PDX_CACHE_HOME`）。
`--check` 只做启动前自检；离屏运行用 `QT_QPA_PLATFORM=offscreen`。
