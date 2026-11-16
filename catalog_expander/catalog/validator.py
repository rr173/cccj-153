"""输入检查。

所有结构性问题在此阶段一次性发现并抛出 StructuralError，整次构建失败。
校验通过后产出规范化中间结构，构建阶段不再做形状检查。
属性冲突不在这里处理——那是正常输出。
"""
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List, Tuple

from .errors import StructuralError
from .rational import parse_pack_factor

NodePair = Tuple[str, str]
Edge = Tuple[NodePair, NodePair, Fraction]  # parent, child, pack_factor

# 合法声明形式（按属性类型）：
#   single: {"mode": "inherit"|"block"|"single", "value": ...(仅 single)}
#   set:    {"base": "inherit"|"reset", "values": [...](仅 reset),
#            "add": [...], "remove": [...]}
#   set block: {"base": "block"}
_VALID_ATTR_TYPES = ("single", "set")


@dataclass
class ValidDecl:
    """规范化后的单条属性声明。"""

    kind: str
    # single: "inherit" | "block" | "single"
    # set:    "inherit" | "reset" | "block"
    mode: str
    value: Any = None          # single(single) 的标量
    reset_values: tuple = ()   # set(reset) 的完整起始集合
    add: tuple = ()
    remove: tuple = ()
    raw: dict = field(default_factory=dict)


@dataclass
class ValidSpec:
    """校验通过的完整输入。"""

    attributes: Dict[str, str]                 # attr -> single/set
    nodes: List[NodePair]                      # 按输入顺序
    node_index: Dict[NodePair, int]
    declarations: Dict[NodePair, Dict[str, ValidDecl]]
    parents: Dict[NodePair, List[Tuple[NodePair, Fraction]]]
    children: Dict[NodePair, List[NodePair]]
    edges: List[Edge]
    order: List[NodePair]                      # 拓扑序（Kahn）
    raw: dict


def _as_pair(ref: Any, where: str) -> NodePair:
    if not isinstance(ref, (list, tuple)) or len(ref) != 2:
        raise StructuralError(f"{where}: 节点身份必须是 [channel, node_id]")
    channel, node_id = ref
    if not isinstance(channel, str) or not isinstance(node_id, str):
        raise StructuralError(f"{where}: channel/node_id 必须是字符串: {ref!r}")
    return (channel, node_id)


def _validate_single_decl(decl: Any, where: str) -> ValidDecl:
    if not isinstance(decl, dict):
        raise StructuralError(f"{where}: single 声明必须是对象")
    mode = decl.get("mode")
    if mode == "inherit":
        return ValidDecl(kind="single", mode="inherit", raw=decl)
    if mode == "block":
        return ValidDecl(kind="single", mode="block", raw=decl)
    if mode == "single":
        if "value" not in decl:
            raise StructuralError(f"{where}: single 声明缺少 value")
        return ValidDecl(kind="single", mode="single",
                         value=decl["value"], raw=decl)
    raise StructuralError(
        f"{where}: 非法 single 模式 {mode!r}，应为 inherit/block/single"
    )


def _validate_set_decl(decl: Any, where: str) -> ValidDecl:
    if not isinstance(decl, dict):
        raise StructuralError(f"{where}: set 声明必须是对象")
    base = decl.get("base")
    if base == "block":
        _forbid(decl, ("add", "remove", "values"), where, base)
        return ValidDecl(kind="set", mode="block", raw=decl)
    if base == "reset":
        values = decl.get("values")
        if not isinstance(values, list):
            raise StructuralError(f"{where}: reset 必须带完整 values 数组")
        add = decl.get("add", [])
        remove = decl.get("remove", [])
        _check_op_arrays(add, remove, where)
        return ValidDecl(
            kind="set", mode="reset",
            reset_values=tuple(values), add=tuple(add), remove=tuple(remove),
            raw=decl,
        )
    if base == "inherit" or base is None:
        add = decl.get("add", [])
        remove = decl.get("remove", [])
        _check_op_arrays(add, remove, where)
        return ValidDecl(
            kind="set", mode="inherit",
            add=tuple(add), remove=tuple(remove), raw=decl,
        )
    raise StructuralError(
        f"{where}: 非法 set base {base!r}，应为 inherit/reset/block"
    )


def _forbid(decl: dict, keys, where: str, base: str):
    for k in keys:
        if k in decl:
            raise StructuralError(f"{where}: base={base} 不允许出现 {k}")


def _check_op_arrays(add: Any, remove: Any, where: str):
    for name, arr in (("add", add), ("remove", remove)):
        if not isinstance(arr, list):
            raise StructuralError(f"{where}: {name} 必须是数组")
    add_set, rm_set = set(add), set(remove)
    overlap = add_set & rm_set
    if overlap:
        raise StructuralError(
            f"{where}: 同一 set 记录的 add/remove 不允许相交: {sorted(overlap)}"
        )


def validate_spec(spec: Any) -> ValidSpec:
    """校验整个输入；任何结构错误都抛 StructuralError。"""
    if not isinstance(spec, dict):
        raise StructuralError("输入必须是对象")

    # ---- 属性类型表 ----
    attr_schema = spec.get("attributes", {})
    if not isinstance(attr_schema, dict):
        raise StructuralError("attributes 必须是 {attr: single/set} 对象")
    attributes: Dict[str, str] = {}
    for attr, kind in attr_schema.items():
        if not isinstance(attr, str):
            raise StructuralError(f"属性名必须是字符串: {attr!r}")
        if kind not in _VALID_ATTR_TYPES:
            raise StructuralError(
                f"属性 {attr!r} 类型必须是 single 或 set，得到 {kind!r}"
            )
        attributes[attr] = kind

    # ---- 节点 ----
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise StructuralError("nodes 必须是非空数组")
    nodes: List[NodePair] = []
    node_index: Dict[NodePair, int] = {}
    declarations: Dict[NodePair, Dict[str, ValidDecl]] = {}
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            raise StructuralError(f"nodes[{i}] 必须是对象")
        ref = _as_pair(n.get("node"), f"nodes[{i}].node")
        if ref in node_index:
            raise StructuralError(f"重复节点: {ref}")
        node_index[ref] = len(nodes)
        nodes.append(ref)
        node_decls: Dict[str, ValidDecl] = {}
        raw_decls = n.get("declarations", {})
        if not isinstance(raw_decls, dict):
            raise StructuralError(f"节点 {ref}: declarations 必须是对象")
        for attr, decl in raw_decls.items():
            if attr not in attributes:
                raise StructuralError(
                    f"节点 {ref}: 未知属性 {attr!r}（未在 attributes 中声明类型）"
                )
            where = f"节点 {ref} 属性 {attr}"
            kind = attributes[attr]
            node_decls[attr] = (
                _validate_single_decl(decl, where)
                if kind == "single"
                else _validate_set_decl(decl, where)
            )
        declarations[ref] = node_decls

    # ---- 边（允许前向引用到稍后定义的节点）----
    raw_edges = spec.get("edges", [])
    if not isinstance(raw_edges, list):
        raise StructuralError("edges 必须是数组")
    parents: Dict[NodePair, List[Tuple[NodePair, Fraction]]] = {
        n: [] for n in nodes
    }
    children: Dict[NodePair, List[NodePair]] = {n: [] for n in nodes}
    edges: List[Edge] = []
    seen_edges = set()
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict):
            raise StructuralError(f"edges[{i}] 必须是对象")
        parent = _as_pair(e.get("parent"), f"edges[{i}].parent")
        child = _as_pair(e.get("child"), f"edges[{i}].child")
        if parent not in node_index:
            raise StructuralError(
                f"edges[{i}]: 未知父节点 {parent}（未在 nodes 中声明）"
            )
        if child not in node_index:
            raise StructuralError(
                f"edges[{i}]: 未知子节点 {child}（未在 nodes 中声明）"
            )
        if parent == child:
            raise StructuralError(f"edges[{i}]: 自环 {parent}")
        if (parent, child) in seen_edges:
            raise StructuralError(f"edges[{i}]: 重复边 {parent} -> {child}")
        seen_edges.add((parent, child))
        factor = parse_pack_factor(
            e.get("pack_factor", 1), f"edges[{i}] {parent} -> {child}"
        )
        edges.append((parent, child, factor))
        parents[child].append((parent, factor))
        children[parent].append(child)

    # ---- 环检查：Kahn 拓扑排序（确定性顺序，不枚举路径）----
    indegree = {n: len(parents[n]) for n in nodes}
    ready = [n for n in nodes if indegree[n] == 0]
    ready.sort(key=node_index.get)
    order: List[NodePair] = []
    import heapq

    heap = [(node_index[n], n) for n in ready]
    heapq.heapify(heap)
    while heap:
        _, n = heapq.heappop(heap)
        order.append(n)
        for c in children[n]:
            indegree[c] -= 1
            if indegree[c] == 0:
                heapq.heappush(heap, (node_index[c], c))
    if len(order) != len(nodes):
        stuck = [list(n) for n in nodes if indegree[n] > 0]
        raise StructuralError(f"图中存在环，涉及节点: {stuck}")

    return ValidSpec(
        attributes=attributes,
        nodes=nodes,
        node_index=node_index,
        declarations=declarations,
        parents=parents,
        children=children,
        edges=edges,
        order=order,
        raw=spec,
    )
