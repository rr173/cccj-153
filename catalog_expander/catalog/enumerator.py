"""独立小图路径枚举器（仅测试用）。

正式实现按拓扑序合并、绝不枚举路径；本模块故意用朴素 DFS 枚举
每一条根到节点路径，独立重算 single/set/pack 语义，作为手写预期
之外的交叉核对。仅适用于路径数量可控的小图。
"""
from fractions import Fraction
from typing import Any, Dict, List, Tuple

from .rational import frac_str
from .validator import ValidDecl, validate_spec

# 路径上的属性快照：(status, value)
Snap = Tuple[str, Any]
VALUE, ABSENT, BLOCKED, CONFLICT = "value", "absent", "blocked", "conflict"


def _single_inherit(snaps: List[Snap]) -> Snap:
    relevant = [s for s in snaps if s[0] != ABSENT]
    if not relevant:
        return (ABSENT, None)
    statuses = {s[0] for s in relevant}
    values = {s[1] for s in relevant if s[0] == VALUE}
    if CONFLICT in statuses or (BLOCKED in statuses and VALUE in statuses) \
            or len(values) > 1:
        return (CONFLICT, None)
    if VALUE in statuses:
        return (VALUE, next(s[1] for s in relevant if s[0] == VALUE))
    return (BLOCKED, None)


def _set_inherit(snaps: List[Snap]) -> Snap:
    relevant = [s for s in snaps if s[0] != ABSENT]
    if not relevant:
        return (ABSENT, None)
    statuses = {s[0] for s in relevant}
    if CONFLICT in statuses:
        return (CONFLICT, None)
    if BLOCKED in statuses:
        return (BLOCKED, None) if statuses == {BLOCKED} else (CONFLICT, None)
    union = sorted({v for s in relevant for v in s[1]})
    return (VALUE, tuple(union))


def _apply_single(decl: ValidDecl, snap: Snap) -> Snap:
    if decl is None or decl.mode == "inherit":
        return snap
    if decl.mode == "single":
        return (VALUE, decl.value)
    return (BLOCKED, None)


def _apply_set(decl: ValidDecl, snap: Snap) -> Snap:
    if decl is None:
        return snap
    if decl.mode == "block":
        return (BLOCKED, None)
    if decl.mode == "reset":
        # reset 从指定集合起算，覆盖父 conflict/blocked
        base = set(decl.reset_values)
        result = sorted((base | set(decl.add)) - set(decl.remove))
        return (VALUE, tuple(result))
    # inherit + add/remove 不能覆盖父冲突
    if snap[0] == CONFLICT:
        return snap
    if snap[0] == BLOCKED:
        if not decl.add and not decl.remove:
            return snap
        return (CONFLICT, None)  # blocked + add/remove 语义冲突
    base = set(snap[1]) if snap[0] == VALUE else set()
    result = sorted((base | set(decl.add)) - set(decl.remove))
    return (VALUE, tuple(result))


def enumerate_reference(spec: dict) -> Dict[Tuple[str, str], dict]:
    """枚举所有根->节点路径后独立重算，返回每个节点的预期属性与包装。"""
    v = validate_spec(spec)
    roots = [n for n in v.nodes if not v.parents[n]]

    # DFS 收集每条根到节点路径：路径节点序列 + 边系数序列
    paths: Dict[tuple, List[List[tuple]]] = {n: [] for n in v.nodes}
    edge_factors: Dict[Tuple, Fraction] = {
        (p, c): f for (p, c, f) in v.edges
    }

    def dfs(node, node_path, factor_path):
        paths[node].append((list(node_path), list(factor_path)))
        for child in v.children[node]:
            dfs(child, node_path + [child],
                factor_path + [edge_factors[(node, child)]])

    for r in roots:
        dfs(r, [r], [])

    expected: Dict[tuple, dict] = {}
    for n in v.nodes:
        per_path_attrs: Dict[str, List[Snap]] = {a: [] for a in v.attributes}
        for node_path, _ in paths[n]:
            snaps: Dict[str, Snap] = {
                a: (ABSENT, None) for a in v.attributes
            }
            for cur in node_path:
                decls = v.declarations[cur]
                for attr, kind in v.attributes.items():
                    decl = decls.get(attr)
                    snaps[attr] = (
                        _apply_single(decl, snaps[attr])
                        if kind == "single"
                        else _apply_set(decl, snaps[attr])
                    )
            for attr in v.attributes:
                per_path_attrs[attr].append(snaps[attr])

        attrs: Dict[str, Snap] = {}
        for attr, kind in v.attributes.items():
            snaps = per_path_attrs[attr]
            attrs[attr] = (
                _single_inherit(snaps) if kind == "single"
                else _set_inherit(snaps)
            )

        pack_factors = set()
        for _, factor_path in paths[n]:
            total = Fraction(1, 1)
            for f in factor_path:
                total *= f
            pack_factors.add(total)
        pack = (
            ("value", next(iter(pack_factors)))
            if len(pack_factors) == 1
            else ("conflict", None)
        )
        expected[n] = {"attrs": attrs, "pack": pack,
                       "path_count": len(paths[n])}
    return expected
