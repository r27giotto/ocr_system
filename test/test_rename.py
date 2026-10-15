# rename_by_ocr.py
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 请先把 "import os.txt" 重命名为 ocr_recognizer.py
from test_ocr2 import (
    collect_image_paths,
    process_image,
    get_rec_engine,
    get_ori_engine,
)

# ==================== 配置 ====================
INPUT_PATH = r"E:\Python Project\project_0\data\dataset1_2026_10_15"
# =============================================

# 用于剥掉已有的 "-数字" 结尾，避免重复运行叠加
SUFFIX_RE = re.compile(r"-\d+$")


# ==================== 工具函数 ====================

def _sanitize_filename(filepath):
    """
    去掉文件名里第一个 '_' 及其左边的内容（仅当左边含非 ASCII 时）。
    例: '10时40分12_T2_TAG1046548825-41.png' -> 'T2_TAG1046548825-41.png'
        'img_1.jpg'                            -> 不变（左边是 ASCII）
        'T2_TAG_1.png'                         -> 不变（左边是 ASCII）
        '中文没有下划线.png'                     -> 不变（没有 '_'，无从下刀）
    """
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    if '_' not in basename:
        return filepath

    head, _, tail = basename.partition('_')
    if head.isascii() or not tail:
        return filepath

    return os.path.join(dirname, tail)


def _unique_path(target_path, current_path):
    """目标已存在时，追加 _1 / _2 ... 避免覆盖"""
    if not os.path.exists(target_path):
        return target_path
    if os.path.abspath(target_path) == os.path.abspath(current_path):
        return target_path

    root, ext = os.path.splitext(target_path)
    i = 1
    while True:
        cand = f"{root}_{i}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


def _strip_chinese_prefix(img_path):
    """进 OpenCV 前先把中文前缀甩掉，返回新路径（无变化则返回原路径）"""
    new_path = _sanitize_filename(img_path)
    if os.path.abspath(new_path) == os.path.abspath(img_path):
        return img_path

    target = _unique_path(new_path, img_path)
    try:
        os.rename(img_path, target)
        print(f"  [预处理] {os.path.basename(img_path)} "
              f"-> {os.path.basename(target)}")
        return target
    except OSError as e:
        print(f"  [预处理] 重命名失败: {e}")
        return img_path


# ==================== 主流程 ====================

def rename_images(input_path):
    paths = collect_image_paths(input_path)
    if not paths:
        print(f"未找到图片: {input_path}")
        return

    print(f"共找到 {len(paths)} 张图片\n")

    # 预热模型
    get_rec_engine()
    get_ori_engine()

    renamed = skipped = 0
    t0 = time.perf_counter()

    for i, img_path in enumerate(paths, 1):
        print(f"[{i}/{len(paths)}] {os.path.basename(img_path)}")

        # ① 预处理：去掉中文前缀（含第一个 '_'）
        img_path = _strip_chinese_prefix(img_path)

        # ② OpenCV 识别（复用原脚本）
        record, _ = process_image(img_path)
        num = record.get("number", "")
        fname = os.path.basename(img_path)

        if not num:
            print(f"  -> 未识别 (status={record['status']})，跳过")
            skipped += 1
            continue

        # ③ 拼接结果：base + "-" + 数字 + ext
        dirname = os.path.dirname(img_path)
        base, ext = os.path.splitext(fname)
        clean_base = SUFFIX_RE.sub("", base)       # 去掉旧的 -数字
        new_name = f"{clean_base}-{num}{ext}"
        target = _unique_path(os.path.join(dirname, new_name), img_path)
        new_name = os.path.basename(target)

        if os.path.abspath(target) == os.path.abspath(img_path):
            print(f"  -> 已是 {new_name}，跳过")
            skipped += 1
            continue

        try:
            os.rename(img_path, target)
            print(f"  -> {new_name}")
            renamed += 1
        except OSError as e:
            print(f"  -> 重命名失败: {e}")
            skipped += 1

    print(f"\n===== 汇总 =====")
    print(f"重命名: {renamed} 张")
    print(f"跳过  : {skipped} 张")
    print(f"耗时  : {time.perf_counter() - t0:.2f} s")


if __name__ == "__main__":
    rename_images(INPUT_PATH)