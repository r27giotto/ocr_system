# test_ocr2.py
import os
import csv
import time
import math
import cv2
import numpy as np
from paddlex import create_model

# ============ 环境变量 ============
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["MKL_NUM_THREADS"] = "8"
cv2.setNumThreads(2)

# ============ 全局单例 ============
_rec_engine = None
_ori_engine = None
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def get_rec_engine():
    global _rec_engine
    if _rec_engine is None:
        print("正在加载纯识别模型（仅首次）...")
        _rec_engine = create_model("PP-OCRv6_small_rec", device="gpu:0")
        print("识别模型加载完成")
    return _rec_engine


def get_ori_engine():
    global _ori_engine
    if _ori_engine is None:
        print("正在加载文本行方向分类模型（仅首次）...")
        _ori_engine = create_model("PP-LCNet_x1_0_textline_ori", device="gpu:0")
        print("方向分类模型加载完成")
    return _ori_engine


# ============ 配置 ============
INPUT_PATH = r"E:\ocr_system_img\test3"
OUTPUT_CSV = r"E:\ocr_system_img\test3\results.csv"
VIS_DIR = None
# VIS_DIR    = r"E:\Python Project\project_0\data\test3\vis"

TARGET_NUMBERS = {'12', '19', '20', '25', '37', '41', '43'}

CONF_THRESHOLD = 0.5     # ★ 0.6 → 0.5：聚合分里弱票贡献极小，放宽准入门槛
ROI_SIZE = 116
SCALE = 1.0

# ★ 加入 ±90°
# ANGLES = (180, -90, -80, -70, -60, -50, -40, -30, -20, -10, 0,
#           10, 20, 30, 40, 50, 60, 70, 80, 90)
ANGLES = (-90, -60, -45, -30, 0, 30, 45, 60, 90, 180)
ORDERED_ANGLES = sorted(ANGLES, key=lambda a: abs(a))

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

# ★ 调试开关：打开后打印每个数字的聚合分
DEBUG_AGGREGATE = True

# ★ 删除 EARLY_EXIT_CONF —— 聚合方案里没有早退

VALID_MIN, VALID_MAX = 1, 48


# ============ 工具函数 ============
def collect_image_paths(path):
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        return [
            os.path.join(path, n)
            for n in sorted(os.listdir(path))
            if n.lower().endswith(IMG_EXTS)
        ]
    return []


def find_center_and_crop(gray):
    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((5, 5), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    (cx, cy), r = cv2.minEnclosingCircle(largest)
    cx, cy, r = int(cx), int(cy), int(r)

    if r < 20 or r > 200:
        return None

    half = ROI_SIZE // 2
    x1, y1 = max(0, cx - half), max(0, cy - half)
    x2, y2 = min(gray.shape[1], cx + half), min(gray.shape[0], cy + half)
    if x2 - x1 < ROI_SIZE or y2 - y1 < ROI_SIZE:
        return None

    return gray[y1:y2, x1:x2], (cx, cy, r), (x1, y1, x2, y2)


def rotate_and_scale(gray, angle, scale=SCALE):
    """灰度图上旋转 + 缩放（INTER_LINEAR）"""
    h, w = gray.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    M = cv2.getRotationMatrix2D((cx, cy), angle, scale)

    rad = math.radians(angle)
    cos_a, sin_a = abs(math.cos(rad)), abs(math.sin(rad))
    new_w = int(scale * (h * sin_a + w * cos_a))
    new_h = int(scale * (h * cos_a + w * sin_a))

    M[0, 2] += new_w / 2.0 - cx
    M[1, 2] += new_h / 2.0 - cy

    return cv2.warpAffine(gray, M, (new_w, new_h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


def _parse_rec_output(result):
    """兼容 PaddleX 多种格式，返回 [(text, score), ...]"""
    items = []
    if result is None:
        return items

    def _walk(obj):
        if obj is None:
            return
        if isinstance(obj, dict):
            if "rec_text" in obj or "rec_texts" in obj:
                texts = obj.get("rec_texts", None)
                scores = obj.get("rec_scores", None)
                if texts is not None and scores is not None:
                    for t, s in zip(texts, scores):
                        items.append((t, float(s)))
                else:
                    items.append((obj.get("rec_text", ""),
                                  float(obj.get("rec_score", 0.0))))
            else:
                for v in obj.values():
                    _walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _walk(v)
        else:
            for attr in ("rec_texts", "rec_text"):
                if hasattr(obj, attr):
                    texts = getattr(obj, "rec_texts", None)
                    scores = getattr(obj, "rec_scores", None)
                    if texts is not None and scores is not None:
                        for t, s in zip(texts, scores):
                            items.append((t, float(s)))
                    else:
                        items.append((getattr(obj, "rec_text", ""),
                                      float(getattr(obj, "rec_score", 0.0))))
                    return

    _walk(result)
    return items


def _parse_ori_output(result):
    """解析方向分类结果，返回 0（正立）或 1（倒置 180°）"""
    if result is None:
        return 0

    def _get(obj, keys, default=None):
        if isinstance(obj, dict):
            for k in keys:
                if k in obj:
                    return obj[k]
        else:
            for k in keys:
                if hasattr(obj, k):
                    return getattr(obj, k)
        return default

    class_ids = _get(result, ["class_ids", "class_id"])
    if class_ids is not None:
        try:
            arr = np.asarray(class_ids).flatten()
            if arr.size > 0:
                return int(arr[0])
        except (ValueError, TypeError):
            pass

    for cand in (_get(result, ["label_names", "label_name"]),
                 _get(result, ["label"])):
        if cand is None:
            continue
        name = cand[0] if isinstance(cand, (list, tuple)) else cand
        s = str(name).lower()
        if "180" in s:
            return 1
        if "0" in s:
            return 0

    return 0


def _build_variants(roi):
    """生成所有角度变体（0° 直接用原 ROI，不放大）"""
    variants = []
    for angle in ORDERED_ANGLES:
        if angle == 0:
            img = roi
        else:
            img = rotate_and_scale(roi, angle, SCALE)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        variants.append((img, angle))
    return variants


def _in_valid_range(number_str):
    """判断数字字符串解析后是否落在 [VALID_MIN, VALID_MAX] 内"""
    try:
        n = int(number_str)
    except (ValueError, TypeError):
        return False
    return VALID_MIN <= n <= VALID_MAX


# ============ 数字聚合 ============
def _aggregate_by_number(candidates, threshold=CONF_THRESHOLD):
    """按数字把候选分组聚合。

    candidates: [(text, score, angle), ...]
    返回按 [聚合分, 最高分, 票数] 降序排序的列表：
        [(num, agg_score, max_score, votes), ...]

    聚合分 = Σ(score - threshold)，即每张票**高出准入门槛的那部分**之和。

    为什么不是简单的 Σscore：Σscore 奖励的是「票数」，不看票的强弱，
    于是「3 张勉强及格的弱票」会压过「2 张 0.9997 的强票」——
    实测 `project_0\\data\\test3\\20.png` 就是这样被判成 '2' 的
    （'2': 3 票 0.7407/0.7465/0.5999 = 2.0871，
      '20': 2 票 0.9997/0.9993 = 1.9990）。减去噪声底后：
    '2' = 0.5871 vs '20' = 0.9990，正确答案胜出。

    减去 threshold 的效果：弱票几乎不贡献证据，强票贡献很多，
    同时仍然保留「多角度互证」的性质 —— 两张 0.8 的票
    （0.3+0.3=0.6）依然胜过一次 0.9 的票（0.4）。
    """
    groups = {}                        # num -> [scores...]
    for text, score, angle in candidates:
        groups.setdefault(text, []).append(score)

    stats = []
    for num, scores in groups.items():
        # 聚合分：只累计高出准入门槛的部分（准入保证每项 >= 0）。
        # 四舍五入到 6 位去掉浮点尾差 —— 否则「边际分相同 → 比票数」这一级
        # 会被 1e-16 的误差抢先决定（0.9+0.9-1.0 与 0.9+0.7+0.7-1.5 本是同一个数）。
        agg   = round(sum(s - threshold for s in scores), 6)
        max_s = max(scores)                       # 最高单次分
        votes = len(scores)                       # 有效票数
        stats.append((num, agg, max_s, votes))

    # 主键=聚合分；次键=最高分；再次=票数
    stats.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    return stats


# ============ 核心：多角度识别 + 数字聚合 ============
def ocr_best_result(roi):
    """
    逐角度推理，收集全部候选，按「数字聚合分」排序取结果。

    1. 构建变体（按 |angle| 升序）
    2. 每个变体：方向分类 → 必要时转 180° → 识别
    3. 过滤低于阈值的、非数字的、'0'
    4. **跑完全部角度后**再做聚合（见 `_aggregate_by_number`）——
       这里不再有旧版的早退：聚合分要靠各个角度的票累加，
       0° 就返回等于放弃后面的票。
    5. 取聚合分最高的、且落在 [VALID_MIN, VALID_MAX] 的数字；
       返回它在所有票里置信度最高的那一次的角度。

    返回 (num, best_score, best_angle)；无有效候选则 None。
    """
    rec = get_rec_engine()
    ori = get_ori_engine()
    variants = _build_variants(roi)
    candidates = []

    for img, angle in variants:
        ori_res = list(ori.predict([img]))
        fixed = img
        if ori_res and _parse_ori_output(ori_res[0]) == 1:
            fixed = cv2.rotate(img, cv2.ROTATE_180)

        rec_res = list(rec.predict([fixed]))
        if not rec_res:
            continue

        for text, score in _parse_rec_output(rec_res[0]):
            if score < CONF_THRESHOLD:
                continue
            cleaned = "".join(ch for ch in text if ch.isdigit())
            if not cleaned:
                continue
            if cleaned == "0":                # ★ 扔掉 0，不进候选池
                continue
            candidates.append((cleaned, score, angle))

    if not candidates:
        return None

    stats = _aggregate_by_number(candidates, CONF_THRESHOLD)

    if DEBUG_AGGREGATE:
        for num, agg, mx, cnt in stats:
            print(f"    [聚合] {num!r}: margin={agg:.4f}  "
                  f"max={mx:.4f}  votes={cnt}")

    # 取第一个（聚合分最高的）且落在有效范围内的数字
    for num, agg, mx, cnt in stats:
        if not _in_valid_range(num):
            continue
        # 该数字命中过的所有角度里，挑置信度最高的那个
        best_score, best_angle = max(
            ((s, a) for n, s, a in candidates if n == num),
            key=lambda x: x[0],
        )
        return (num, best_score, best_angle)

    return None


# ============ 可视化 ============
def _build_vis(img, crop_info, roi, num, conf, angle):
    """在原图上画 ROI 红框 + ROI 旁小标签"""
    vis = img.copy()
    (cx, cy, r), (x1, y1, x2, y2) = crop_info[1], crop_info[2]
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 4)

    label = f"{num}"
    lfs, lth = 0.8, 2
    (lw, lht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, lfs, lth)
    ly = y1 - 8 if y1 - 8 - lht > 0 else min(y2 + lht + 8, vis.shape[0] - 5)
    cv2.rectangle(vis, (x1, ly - lht - 4), (x1 + lw + 8, ly + 4),
                  (255, 255, 255), -1)
    cv2.putText(vis, label, (x1 + 4, ly),
                cv2.FONT_HERSHEY_SIMPLEX, lfs, (0, 0, 255), lth)

    return vis


# ============ 单张图片处理 ============
def process_image(img_path, vis_dir=None):
    start_time = time.perf_counter()
    record = {
        "filename": os.path.basename(img_path),
        "number": "", "confidence": 0.0, "angle": "",
        "hit": False, "status": "ok", "elapsed_ms": 0.0,
    }

    img = cv2.imread(img_path)
    if img is None:
        record["status"] = "read_failed"
        record["elapsed_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
        return record, None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    enhanced = _clahe.apply(gray)

    crop_info = find_center_and_crop(enhanced)
    if crop_info is None:
        record["status"] = "circle_not_found"
        record["elapsed_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
        return record, img

    roi, (cx, cy, r), (x1, y1, x2, y2) = crop_info
    best = ocr_best_result(roi)

    if best is None:
        record["status"] = "no_number"
        record["elapsed_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
        return record, img

    # ★ 新版返回三元组 (num, best_score, best_angle)
    num, conf, angle = best
    record["number"] = num
    record["confidence"] = round(conf, 4)
    record["angle"] = angle
    record["hit"] = num in TARGET_NUMBERS

    if vis_dir:
        os.makedirs(vis_dir, exist_ok=True)
        vis = _build_vis(img, crop_info, roi, num, conf, angle)
        out_name = os.path.splitext(record["filename"])[0] + "_vis.jpg"
        cv2.imwrite(os.path.join(vis_dir, out_name), vis,
                    [cv2.IMWRITE_JPEG_QUALITY, 90])

    record["elapsed_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
    return record, img


# ============ 主流程 ============
def main():
    total_start = time.perf_counter()

    image_paths = collect_image_paths(INPUT_PATH)
    if not image_paths:
        print(f"未找到图片：{INPUT_PATH}")
        return

    print(f"共找到 {len(image_paths)} 张图片\n")

    get_rec_engine()
    get_ori_engine()

    records = []
    for i, img_path in enumerate(image_paths, 1):
        print(f"[{i}/{len(image_paths)}] 处理中: {os.path.basename(img_path)}")
        record, _ = process_image(img_path, vis_dir=VIS_DIR)
        records.append(record)
        print(f"    → 数字: {record['number'] or '无'}  "
              f"置信度: {record['confidence']}  "
              f"命中: {record['hit']}  "
              f"状态: {record['status']}  "
              f"耗时: {record['elapsed_ms']:.1f} ms")

    csv_dir = os.path.dirname(OUTPUT_CSV)
    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)

    fieldnames = ["filename", "number", "confidence", "angle",
                  "hit", "status", "elapsed_ms"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    times = [r["elapsed_ms"] for r in records]
    print("\n===== 汇总 =====")
    print(f"总图片数: {len(records)}")
    print(f"识别成功: {sum(1 for r in records if r['status'] == 'ok')}")
    print(f"命中目标: {sum(1 for r in records if r['hit'])}")
    if times:
        print(f"平均耗时: {sum(times) / len(times):.1f} ms/张")
        print(f"最快: {min(times):.1f} ms    最慢: {max(times):.1f} ms")
    print(f"整体耗时: {time.perf_counter() - total_start:.2f} s")
    print(f"结果已保存到: {OUTPUT_CSV}")
    if VIS_DIR:
        print(f"可视化结果已保存到: {VIS_DIR}")


if __name__ == "__main__":
    main()