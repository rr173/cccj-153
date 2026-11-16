"""包装系数（正有理数）解析与序列化。"""
from fractions import Fraction
import re

from .errors import StructuralError

# 仅接受整数或 "n/d" 形式；小数、负数、零、零分母均为坏有理数。
_RATIONAL_RE = re.compile(r"^[0-9]+(?:/[0-9]+)?$")


def parse_pack_factor(raw, where: str) -> Fraction:
    """把边上的 pack_factor 解析为正 Fraction。

    接受：正 int、正 Fraction、"n" 或 "n/d" 形式的字符串。
    拒绝：bool、float、负数、零、零分母、无法识别的字符串。
    """
    if isinstance(raw, bool):
        raise StructuralError(f"{where}: 布尔值不是合法有理数: {raw!r}")
    if isinstance(raw, int):
        if raw <= 0:
            raise StructuralError(f"{where}: 包装系数必须为正数: {raw!r}")
        return Fraction(raw, 1)
    if isinstance(raw, Fraction):
        if raw <= 0:
            raise StructuralError(f"{where}: 包装系数必须为正数: {raw!r}")
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not _RATIONAL_RE.match(s):
            raise StructuralError(f"{where}: 坏有理数: {raw!r}")
        if "/" in s:
            num_s, den_s = s.split("/", 1)
            num, den = int(num_s), int(den_s)
            if den == 0:
                raise StructuralError(f"{where}: 零分母有理数: {raw!r}")
        else:
            num, den = int(s), 1
        if num <= 0:
            raise StructuralError(f"{where}: 包装系数必须为正数: {raw!r}")
        return Fraction(num, den)
    raise StructuralError(f"{where}: 无法识别的有理数类型: {raw!r}")


def frac_str(value: Fraction) -> str:
    """规范字符串：分母为 1 时输出整数，否则 n/d。"""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"
