#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test/run_app.py —— 项目启动 / 环境自检脚本。

用法（用哪个 python 启动都行，脚本会自己切到项目虚拟环境）:

    python test/run_app.py              # 自检 + 启动界面
    python test/run_app.py --check      # 只自检，不启动界面
    python test/run_app.py --no-check   # 跳过自检，直接启动


为什么需要这个脚本 —— 直接 `python main.py` 会踩三个坑：

  1. 依赖只装在 .venv 里。系统默认的是 E:\\Python313\\python.exe，
     它没有 PyQt6 / paddlex，import 就会失败。
  2. main.py 用相对路径 load_config("config.yaml")，
     必须在项目根目录下运行，否则找不到配置。
  3. main.py 要 import app.* / ui.*，而直接运行 test/ 下的脚本时，
     sys.path 上是 test/ 而不是项目根目录，import 一样会失败。

本脚本把这三件事都处理掉，并在启动前报告一遍环境状态。

注意：模型是在界面上点「加载模型」按钮时才加载的（不是在启动时），
所以就算模型目录读不了，界面本身仍然能打开 —— 自检里这种情况按警告处理。
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 环境变量：必须在 import cv2 / paddlex 之前设置
# ---------------------------------------------------------------------------
os.environ.setdefault("OMP_NUM_THREADS", "8")
os.environ.setdefault("MKL_NUM_THREADS", "8")
# 关掉 PaddleX 的联网连通性检查：会白等好几秒，模型已在本地时纯属浪费
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# 模型缓存指向项目内的 models/（main.py 里也设了；这里设是为了自检也走同一个目录）。
# PaddleX 在 import 时读取，必须早于任何 paddlex import。
os.environ.setdefault(
    "PADDLE_PDX_CACHE_HOME",
    str(Path(__file__).resolve().parents[1] / "models"),
)

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
if not VENV_PY.exists():  # 非 Windows 兜底
    VENV_PY = VENV_DIR / "bin" / "python"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

REQUIRED_MODULES = [
    ("PyQt6", "GUI 框架"),
    ("cv2", "OpenCV 图像处理"),
    ("numpy", "数值计算"),
    ("yaml", "读取 config.yaml"),
    ("serial", "串口 (pyserial)"),
    ("paddlex", "PaddleX 推理"),
    ("paddle", "PaddlePaddle 后端"),
]

# ---------------------------------------------------------------------------
# 输出助手（只用 ASCII 标记 + 中文，避免控制台编码问题）
# ---------------------------------------------------------------------------
_STATE = {"fail": 0, "warn": 0}


def _ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")
    _STATE["warn"] += 1


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _STATE["fail"] += 1


def _info(msg: str) -> None:
    print(f"         {msg}")


def _head(idx: str, title: str) -> None:
    print(f"\n[{idx}] {title}")


# ---------------------------------------------------------------------------
# 用正确的解释器重跑自己
# ---------------------------------------------------------------------------
def reexec_with_venv_python() -> None:
    """当前解释器不是项目 venv 时，用 venv 的 python 重新执行本脚本。"""
    if not VENV_PY.exists():
        return
    try:
        already = Path(sys.executable).resolve() == VENV_PY.resolve()
    except OSError:
        already = False
    if already:
        return

    print(f"[i] 当前解释器不是项目虚拟环境:")
    print(f"      当前 = {sys.executable}")
    print(f"      切换 = {VENV_PY}")
    rc = subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(rc)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def load_config() -> dict | None:
    if not CONFIG_PATH.is_file():
        _fail(f"找不到配置文件 {CONFIG_PATH}")
        return None
    try:
        import yaml

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        _fail(f"config.yaml 解析失败: {type(e).__name__}: {e}")
        return None


def model_cache_dir() -> Path:
    env = os.environ.get("PADDLE_PDX_CACHE_HOME")
    if env:
        return Path(env).expanduser() / "official_models"
    return Path.home() / ".paddlex" / "official_models"


def check_interpreter() -> None:
    _head("1/5", "解释器与虚拟环境")
    _info(f"可执行文件: {sys.executable}")
    _info(f"Python 版本: {sys.version.split()[0]}")

    try:
        same = Path(sys.executable).resolve() == VENV_PY.resolve()
    except OSError:
        same = False
    if same:
        _ok(f"正在使用项目虚拟环境 {VENV_DIR}")
    else:
        _warn(f"当前不是项目虚拟环境（期望 {VENV_PY}）")

    if sys.version_info < (3, 12):
        _fail("需要 Python >= 3.12（见 pyproject.toml 的 requires-python）")
    else:
        _ok("Python 版本满足 >= 3.12")


def check_config() -> dict | None:
    _head("2/5", "目录与配置")
    if PROJECT_ROOT.is_dir():
        _ok(f"项目根目录 {PROJECT_ROOT}")
    else:
        _fail(f"项目根目录不存在: {PROJECT_ROOT}")
        return None

    cfg = load_config()
    if cfg is None:
        return None
    _ok("config.yaml 解析成功")

    for key in ("app", "target", "models", "recognizer", "preprocess"):
        if key not in cfg:
            _warn(f"config.yaml 缺少顶层键 `{key}`")

    models = cfg.get("models", {}) or {}
    target = cfg.get("target", {}) or {}
    rec = cfg.get("recognizer", {}) or {}
    angles = rec.get("angles") or []

    _info(f"默认识别模型: {models.get('default_rec')}")
    _info(f"默认方向模型: {models.get('default_ori')}")
    _info(f"目标数字集合: {target.get('numbers')}  有效范围 [{target.get('valid_min')}, {target.get('valid_max')}]")
    _info(f"候选角度 {len(angles)} 个: {angles}")
    return cfg


def check_imports() -> None:
    _head("3/5", "依赖包")
    for mod, desc in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            _ok(f"{mod:<8} {desc}")
        except Exception as e:
            _fail(f"{mod:<8} {desc}  ->  {type(e).__name__}: {e}")


def check_models(cfg: dict | None) -> None:
    _head("4/5", "模型缓存")
    cache = model_cache_dir()
    _info(f"缓存目录: {cache}")

    if not cache.is_dir():
        _warn("缓存目录不存在；首次加载模型需要联网下载")
        return

    models = ((cfg or {}).get("models", {}) or {})
    names: list[str] = []
    for key in ("default_rec", "default_ori"):
        n = models.get(key)
        if n and n not in names:
            names.append(n)

    if not names:
        _warn("配置里没有 default_rec / default_ori，跳过检查")
        return

    for name in names:
        d = cache / name
        if not d.is_dir():
            _warn(f"{name} 未下载（选中它时需要联网）")
            continue
        try:
            os.listdir(d)
            _ok(f"{name} 可读")
        except PermissionError as e:
            _warn(f"{name} 拒绝访问 -> {e}")
            _info("这是 Windows 文件权限问题，不是代码问题。")
            _info("点「加载模型」会失败；详见设计文档 docs/superpowers/specs/ 下 §11 阻塞项 1。")
        except Exception as e:
            _warn(f"{name} 读取异常 -> {type(e).__name__}: {e}")


def check_runtime_dirs(cfg: dict | None) -> None:
    _head("5/5", "运行目录")
    app_cfg = ((cfg or {}).get("app", {}) or {})

    log_dir = PROJECT_ROOT / str(app_cfg.get("log_dir", "./logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / ".write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        _ok(f"日志目录可写 {log_dir}")
    except Exception as e:
        _fail(f"日志目录不可写 {log_dir} -> {type(e).__name__}: {e}")

    csv_out = PROJECT_ROOT / str(app_cfg.get("csv_output", "./logs/results.csv"))
    try:
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        _ok(f"CSV 输出路径 {csv_out}")
    except Exception as e:
        _fail(f"CSV 输出路径不可用 {csv_out} -> {type(e).__name__}: {e}")

    src = ((cfg or {}).get("source", {}) or {})
    _info(f"配置中的输入源: type={src.get('type')} folder_path={src.get('folder_path')!r}")


def preflight() -> bool:
    """返回 True 表示可以启动。"""
    print("=" * 64)
    print("  OCR 识别系统 —— 启动前自检")
    print("=" * 64)

    check_interpreter()
    cfg = check_config()
    check_imports()
    check_models(cfg)
    check_runtime_dirs(cfg)

    print("\n" + "-" * 64)
    if _STATE["fail"]:
        print(f"  自检结果: {_STATE['fail']} 项失败, {_STATE['warn']} 项警告 —— 不建议启动")
    elif _STATE["warn"]:
        print(f"  自检结果: 通过, 但有 {_STATE['warn']} 项警告")
    else:
        print("  自检结果: 全部通过")
    print("-" * 64)
    return _STATE["fail"] == 0


# ---------------------------------------------------------------------------
# 启动界面
# ---------------------------------------------------------------------------
def launch_gui() -> None:
    # main.py 依赖这两件事：项目根在 sys.path 上、工作目录在项目根
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(PROJECT_ROOT)

    print(f"\n启动界面 …  工作目录 = {Path.cwd()}")
    import main as entry  # noqa: E402  （必须在 sys.path / cwd 就位之后）

    entry.main()


# ---------------------------------------------------------------------------
def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # 防止中文打印炸掉
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="启动 OCR 识别系统（自动切换到项目虚拟环境）",
    )
    parser.add_argument("-c", "--check", action="store_true",
                       help="只做环境自检，不启动界面")
    parser.add_argument("--no-check", action="store_true",
                       help="跳过自检，直接启动界面")
    args = parser.parse_args()

    reexec_with_venv_python()

    ok = True
    if not args.no_check:
        ok = preflight()

    if args.check:
        print()
        return 0 if ok else 1

    if not ok:
        print("\n自检未通过，已中止。要强制启动请加 --no-check。\n")
        return 1

    try:
        launch_gui()
    except SystemExit as e:
        return int(e.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
