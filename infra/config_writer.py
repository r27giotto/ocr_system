# -*- coding: utf-8 -*-
"""定点改写 `config.yaml` 里的单个标量值，**保住注释、顺序和其他段落**。

为什么不用 `yaml.safe_dump` 整文件重写：`config.yaml` 里满是中文注释，
PyYAML 读进来再写出去会把注释**全部抹掉**，一份自解释的配置就退化成裸数据了。

所以这里的做法是「找到那一行，只换冒号后面的值」：
    max_items: 10          # 历史面板保留条数
    ^^^^^^^^^^^^^ 只动这一段，后面的注释原样留着

找不到目标键时**抛异常并且不写文件** —— 宁可报错，也不要静默把配置改坏。
"""
from __future__ import annotations

import io
import os
import re
from typing import Union

import yaml

Scalar = Union[int, float, bool, str]

_SECTION_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z_][\w.\-]*)[ \t]*:[ \t]*(?P<rest>.*)$")


class ConfigWriteError(RuntimeError):
    """定位不到目标键，或写入后回读校验不一致。"""


def _format_scalar(value: Scalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = str(value)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text
    return '"%s"' % text.replace('"', '\\"')


def _split_trailing_comment(rest: str) -> tuple[str, str]:
    """把 `10   # 注释` 拆成 (`10   `, `# 注释`)。值里带引号含 # 的情况本题用不到。"""
    best = None
    for marker in (" #", "\t#"):
        pos = rest.find(marker)
        if pos != -1 and (best is None or pos < best):
            best = pos
    if best is None:
        return rest, ""
    return rest[:best], rest[best:]


def _locate(lines: list[str], section: str, key: str) -> int:
    """返回目标行在 lines 里的下标（0 基）。"""
    in_section = False
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line.rstrip("\r\n"))
        if not m:
            continue
        is_top = m.group("indent") == ""
        if is_top:
            in_section = m.group("key") == section
            continue
        if in_section and m.group("key") == key:
            return i
    raise ConfigWriteError(
        "在 %s: 段里找不到键 %r（不会改动文件）" % (section, key))


def set_value(config_path: str, dotted_key: str, value: Scalar) -> None:
    """把 `config.yaml` 里 `dotted_key`（形如 `history.max_items`）的值改成 `value`。

    成功返回 None；定位不到或回读校验失败抛 `ConfigWriteError`（文件保持原样）。
    """
    if "." not in dotted_key:
        raise ConfigWriteError("dotted_key 必须形如 'section.key'，收到 %r" % (dotted_key,))
    section, key = dotted_key.split(".", 1)

    with io.open(config_path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)

    idx = _locate(lines, section, key)
    m = _SECTION_RE.match(lines[idx])
    if not m:  # pragma: no cover - _locate 已经保证了能匹配
        raise ConfigWriteError("内部错误：目标行无法解析")

    value_part, comment = _split_trailing_comment(m.group("rest"))
    trailing_ws = value_part[len(value_part.rstrip()):]
    new_line = "%s%s: %s%s%s" % (
        m.group("indent"), key, _format_scalar(value), trailing_ws, comment)
    if new_line == lines[idx]:
        return
    lines[idx] = new_line

    new_text = newline.join(lines)
    tmp = config_path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    os.replace(tmp, config_path)

    # 回读校验：值真的变成我们要的那个，且整份文件仍然能被 YAML 解析
    with io.open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    node = data
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigWriteError("回读校验失败：%s 不见了" % (dotted_key,))
        node = node[part]
    if node != value:
        raise ConfigWriteError(
            "回读校验失败：%s 期望 %r，实际 %r" % (dotted_key, value, node))
