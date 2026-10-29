from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2

from core.engine import EngineManager
from core.parsers import parse_ori_output, parse_rec_output
from core.preprocess import Preprocessor

# 单个候选进入聚合池的门槛。低于它的识别结果直接丢掉，
# 不参与投票 —— 这一步只做「准入」，不做「择优」。
# 它同时还当「噪声底」用：聚合时每张票只按 (score - 这个值) 计入证据，
# 见 _aggregate_by_number。
CONF_THRESHOLD = 0.5


def _aggregate_by_number(candidates, threshold=CONF_THRESHOLD):
    """按数字把候选分组聚合。

    candidates: [(text, score, angle), ...]
    返回按 [聚合分, 最高分, 票数] 降序排序的列表：
        [(num, agg_score, max_score, votes), ...]

    聚合分 = Σ(score - threshold)，即每张票**高出准入门槛的那部分**之和。

    为什么不是简单的 Σscore：Σscore 奖励的是「票数」，不看票的强弱，
    于是「3 张勉强及格的弱票」会压过「2 张 0.9997 的强票」——
    实测 `project_0\\data\\test3\\20.png` 就是这样被判成 '2' 的
    （'2': 3 票 0.7407/0.7465/0.5999 = 2.0871，'
     20': 2 票 0.9997/0.9993 = 1.9990）。减去噪声底后：
    '2' = 0.5871 vs '20' = 0.9990，正确答案胜出。

    减去 threshold 的效果：弱票几乎不贡献证据，强票贡献很多，
    同时仍然保留「多角度互证」的性质 —— 两张 0.8 的票
    （0.3+0.3=0.6）依然胜过一次 0.9 的票（0.4）。
    """
    groups: Dict[str, List[float]] = {}   # num -> [scores...]
    for text, score, angle in candidates:
        groups.setdefault(text, []).append(score)

    stats = []
    for num, scores in groups.items():
        # 聚合分：只累计高出准入门槛的部分（准入保证每项 >= 0）。
        # 四舍五入到 6 位去掉浮点尾差 —— 否则「边际分相同 → 比票数」这一级
        # 会被 1e-16 的误差抢先决定（0.9+0.9-1.0 与 0.9+0.7+0.7-1.5 本是同一个数）。
        agg = round(sum(s - threshold for s in scores), 6)
        max_s = max(scores)                      # 最高单次分
        votes = len(scores)                      # 有效票数
        stats.append((num, agg, max_s, votes))

    # 主键=聚合分；次键=最高分；再次=票数
    stats.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    return stats


@dataclass
class RecognizerConfig:
    angles: Tuple[int, ...] = (-90, -60, -30, 0, 30, 60, 90, 180)
    conf_threshold: float = CONF_THRESHOLD
    valid_min: int = 1
    valid_max: int = 48
    drop_zero: bool = False
    # 打印每个数字的聚合分/最高分/票数。调优阶段打开，稳定后关掉。
    debug_aggregate: bool = False
    # 【已废弃】旧版「0° 且 ≥ 该分数就立即返回」的早退阈值。
    # 聚合逻辑需要跑完所有角度才能投票，早退会丢掉后面的票，
    # 所以这个值不再被读取；保留字段只为让旧 config.yaml 仍能加载。
    early_exit_conf: float = 0.99


class Recognizer:
    def __init__(self, engine: EngineManager, pre: Preprocessor,
                 cfg: RecognizerConfig):
        self.engine = engine
        self.pre = pre
        self.cfg = cfg
        self.rec_model_name = ""
        self.ori_model_name = ""

    def set_models(self, rec_name: str, ori_name: str) -> None:
        self.rec_model_name = rec_name
        self.ori_model_name = ori_name

    def set_angles(self, angles: Tuple[int, ...]) -> None:
        """GUI 角度勾选变化时调用"""
        self.cfg.angles = tuple(sorted(set(angles), key=lambda a: abs(a)))

    def set_conf_threshold(self, v: float) -> None:
        self.cfg.conf_threshold = float(v)

    def recognize(self, roi) -> Optional[Tuple[str, float, int]]:
        """逐角度推理，收集全部候选，按「数字聚合分」排序取结果。

        1. 构建变体（按 |angle| 升序）
        2. 每个变体：方向分类 → 必要时转 180° → 识别
        3. 过滤低于阈值的、非数字的、'0'
        4. **跑完全部角度后**再做聚合（见 `_aggregate_by_number`）——
           这里不再有旧版的早退：聚合分要靠各个角度的票累加，
           0° 就返回等于放弃后面的票。
        5. 取聚合分最高的、且落在 [valid_min, valid_max] 的数字；
           返回它在所有票里置信度最高的那一次的角度。

        返回 (num, best_score, best_angle)；无有效候选则 None。
        """
        rec = self.engine.get_rec(self.rec_model_name)
        ori = self.engine.get_ori(self.ori_model_name)

        variants = self.pre.build_variants(roi, self.cfg.angles)
        candidates = []

        for img, angle in variants:
            ori_res = list(ori.predict([img]))
            fixed = img
            if ori_res and parse_ori_output(ori_res[0]) == 1:
                fixed = cv2.rotate(img, cv2.ROTATE_180)

            rec_res = list(rec.predict([fixed]))
            if not rec_res:
                continue

            for text, score in parse_rec_output(rec_res[0]):
                if score < self.cfg.conf_threshold:
                    continue
                cleaned = "".join(ch for ch in text if ch.isdigit())
                if not cleaned:
                    continue
                if self.cfg.drop_zero and cleaned == "0":
                    continue
                candidates.append((cleaned, score, angle))

        if not candidates:
            return None

        stats = _aggregate_by_number(candidates, self.cfg.conf_threshold)

        if self.cfg.debug_aggregate:
            for num, agg, mx, cnt in stats:
                print(f"    [聚合] {num!r}: margin={agg:.4f}  "
                      f"max={mx:.4f}  votes={cnt}")

        # 取第一个（聚合分最高的）且落在有效范围内的数字
        for num, agg, mx, cnt in stats:
            if not self._in_range(num):
                continue
            # 该数字命中过的所有角度里，挑置信度最高的那个
            best_score, best_angle = max(
                ((s, a) for n, s, a in candidates if n == num),
                key=lambda x: x[0],
            )
            return (num, best_score, best_angle)

        return None

    def _in_range(self, number_str: str) -> bool:
        try:
            n = int(number_str)
        except (ValueError, TypeError):
            return False
        return self.cfg.valid_min <= n <= self.cfg.valid_max
