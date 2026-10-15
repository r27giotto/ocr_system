import numpy as np

def parse_rec_output(result) -> list[tuple[str, float]]:
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

def parse_ori_output(result) -> int:
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