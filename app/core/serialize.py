"""JSON xavfsiz serializer.

numpy 2.x da `numpy.bool` / `int64` / `float64` stdlib json.dumps ni
`Object of type bool is not JSON serializable` bilan yiqitadi.
Barcha DB/Telegram JSON yozuvlari shu modul orqali o'tsin.
"""
from __future__ import annotations

import json
import math
from typing import Any


def to_jsonable(obj: Any) -> Any:
    """Istalgan obyektni json.dumps qabul qiladigan shaklga keltiradi."""
    if obj is None:
        return None
    # bool int ning kichik sinfi — avval tekshiriladi
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]

    # numpy / pandas skalari (numpy 2: type nomi 'bool')
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return to_jsonable(obj.tolist())
        if isinstance(obj, np.generic):
            return to_jsonable(obj.item())
    except Exception:
        pass

    if hasattr(obj, "item") and not isinstance(obj, (bytes, bytearray, memoryview)):
        try:
            shape = getattr(obj, "shape", None)
            if shape is None or shape == ():
                return to_jsonable(obj.item())
        except Exception:
            pass

    return str(obj)


def dumps(obj: Any) -> str:
    """ensure_ascii=False JSON — numpy bool/int/float xavfsiz."""
    return json.dumps(to_jsonable(obj), ensure_ascii=False)
