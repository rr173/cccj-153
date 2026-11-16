"""核心构建器。

在拓扑序上逐节点计算：
  * single 属性：父有效声明合并 -> 本地 single/block 可显式覆盖；
  * set 属性：父有效集合取并 -> 本地 inherit(+add/remove)/reset/block；
  * pack 系数：沿父边乘积累积，同节点多路径结果必须一致。

全部语义共享一张证据图：相同内容的证据节点内容寻址去重，
菱形结构只产生合并节点，绝不枚举根到叶的路径。
"""
from fractions import Fraction
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .errors import StructuralError
from .model import ABSENT, BLOCKED, CONFLICT, VALUE, AttrState, NodeRef, PackState
from .rational import frac_str
from .store import CatalogStore
from .validator import ValidDecl, ValidSpec, validate_spec

# 状态元组：(status, value, evidence_id)；absent 的 evidence_id 恒为 None
State = Tuple[str, Any, Optional[str]]
NodePair = Tuple[str, str]


# ---------------------------------------------------------------- 规范化与证据

def _canon(obj: Any) -> str:
    """确定性序列化，用于证据内容寻址。"""
    if isinstance(obj, dict):
        return "{" + ",".join(
            json.dumps(k, ensure_ascii=False) + ":" + _canon(v)
            for k, v in sorted(obj.items(), key=lambda kv: kv[0])
        ) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_canon(x) for x in obj) + "]"
    return json.dumps(obj, ensure_ascii=False)


class EvidenceSink:
    """共享证据图：内容寻址去重，ID 按首次出现顺序分配。"""

    def __init__(self):
        self.nodes: Dict[str, dict] = {}
        self._hash_to_id: Dict[str, str] = {}

    def add(self, kind: str, payload: dict) -> str:
        payload = json.loads(json.dumps(payload, ensure_ascii=False))
        digest = hashlib.sha256(
            (kind + "|" + _canon(payload)).encode("utf-8")
        ).hexdigest()[:16]
        existing = self._hash_to_id.get(digest)
        if existing is not None:
            return existing
        eid = f"e{len(self.nodes)}"
        self._hash_to_id[digest] = eid
        self.nodes[eid] = {"kind": kind, "payload": payload}
        return eid


# ---------------------------------------------------------------- single 属性

def _combine_single(attr: str, parent_states: List[State],
                    sink: EvidenceSink) -> State:
    """合并所有父节点的有效 single 声明；absent 被忽略。"""
    relevant = [s for s in parent_states if s[0] != ABSENT]
    if not relevant:
        return (ABSENT, None, None)
    if len(relevant) == 1:
        return relevant[0]  # 唯一来源直接传播，不制造冗余证据

    statuses = {s[0] for s in relevant}
    values = {s[1] for s in relevant if s[0] == VALUE}
    if CONFLICT in statuses:
        result_status = CONFLICT
    elif BLOCKED in statuses and VALUE in statuses:
        result_status = CONFLICT  # block 与值并存
    elif len(values) > 1:
        result_status = CONFLICT  # 值不同
    elif VALUE in statuses:
        result_status = VALUE    # 相同值合并证据
    else:
        result_status = BLOCKED  # 全部 block

    payload: Dict[str, Any] = {
        "sources": [s[2] for s in relevant],
        "result_status": result_status,
    }
    if result_status == VALUE:
        value = next(s[1] for s in relevant if s[0] == VALUE)
        payload["value"] = value
    eid = sink.add("single_merge", payload)
    if result_status == VALUE:
        return (VALUE, next(s[1] for s in relevant if s[0] == VALUE), eid)
    return (result_status, None, eid)


def _apply_single_local(node: NodePair, attr: str,
                        decl: Optional[ValidDecl], incoming: State,
                        sink: EvidenceSink) -> State:
    """应用本节点 single 本地声明；inherit/无声明时保持传入状态。"""
    if decl is None or decl.mode == "inherit":
        return incoming
    pair = [node[0], node[1]]
    if decl.mode == "single":
        if incoming[0] == ABSENT:
            eid = sink.add("prim_single", {
                "node": pair, "attr": attr, "form": "single",
                "value": decl.value,
            })
        else:
            # 显式覆盖（含覆盖冲突）：本地值同时作为原声明留档，
            # 被覆盖来源保留在 incoming 中
            local = sink.add("prim_single", {
                "node": pair, "attr": attr, "form": "single",
                "value": decl.value,
            })
            eid = sink.add("single_override", {
                "incoming": incoming[2],
                "local": local,
                "node": pair, "attr": attr, "form": "single",
                "value": decl.value,
            })
        return (VALUE, decl.value, eid)
    # block：显式“不适用”，不得按缺值重新继承
    if incoming[0] == ABSENT:
        eid = sink.add("prim_single", {
            "node": pair, "attr": attr, "form": "block",
        })
    else:
        local = sink.add("prim_single", {
            "node": pair, "attr": attr, "form": "block",
        })
        eid = sink.add("single_override", {
            "incoming": incoming[2],
            "local": local,
            "node": pair, "attr": attr, "form": "block",
        })
    return (BLOCKED, None, eid)


# ---------------------------------------------------------------- set 属性

def _combine_set(attr: str, parent_states: List[State],
                 sink: EvidenceSink) -> State:
    """父有效集合取并；父 block/conflict 按规则汇总；absent 忽略。"""
    relevant = [s for s in parent_states if s[0] != ABSENT]
    if not relevant:
        return (ABSENT, None, None)
    if len(relevant) == 1:
        return relevant[0]

    statuses = {s[0] for s in relevant}
    if CONFLICT in statuses:
        result_status = CONFLICT
    elif BLOCKED in statuses:
        result_status = BLOCKED if statuses == {BLOCKED} else CONFLICT
    else:
        result_status = VALUE

    payload: Dict[str, Any] = {
        "sources": [s[2] for s in relevant],
        "result_status": result_status,
    }
    if result_status == VALUE:
        union = sorted({v for s in relevant for v in s[1]})
        payload["values"] = union
        eid = sink.add("set_merge", payload)
        return (VALUE, tuple(union), eid)
    eid = sink.add("set_merge", payload)
    return (result_status, None, eid)


def _set_op_payload(node: NodePair, attr: str, decl: ValidDecl,
                    incoming: State, override: bool) -> dict:
    return {
        "incoming": incoming[2],
        "node": [node[0], node[1]],
        "attr": attr,
        "base_mode": decl.mode,               # inherit / reset
        "reset_values": list(decl.reset_values),
        "add": list(decl.add),
        "remove": list(decl.remove),
        "override": override,
    }


def _apply_set_local(node: NodePair, attr: str, decl: Optional[ValidDecl],
                     incoming: State, sink: EvidenceSink) -> State:
    # 无声明 / 纯 inherit（无 add/remove）：原样传播，absent/blocked/conflict
    # 均自然向下传递
    if decl is None or (decl.mode == "inherit"
                        and not decl.add and not decl.remove):
        return incoming

    pair = [node[0], node[1]]

    # block：独立记录形式，可覆盖任何传入状态（含父冲突）
    if decl.mode == "block":
        if incoming[0] == ABSENT:
            eid = sink.add("prim_set_block", {"node": pair, "attr": attr})
        else:
            local = sink.add("prim_set_block",
                             {"node": pair, "attr": attr})
            eid = sink.add("set_override", {
                "incoming": incoming[2], "local": local,
                "node": pair, "attr": attr, "form": "block",
            })
        return (BLOCKED, None, eid)

    # reset：从指定集合起算，不继承父值，可覆盖父 conflict/blocked
    if decl.mode == "reset":
        result = (set(decl.reset_values) | set(decl.add)) - set(decl.remove)
        result_sorted = tuple(sorted(result))
        payload = _set_op_payload(node, attr, decl, incoming,
                                  override=incoming[0] != ABSENT)
        payload["result_status"] = VALUE
        payload["result_values"] = list(result_sorted)
        eid = sink.add("set_apply", payload)
        return (VALUE, result_sorted, eid)

    # 以下为 inherit + add/remove：不能覆盖父 conflict/blocked
    if incoming[0] == CONFLICT:
        return incoming
    if incoming[0] == BLOCKED:
        # blocked 上做 add/remove：输入语义冲突，不猜成空集
        payload = _set_op_payload(node, attr, decl, incoming, False)
        payload["result_status"] = CONFLICT
        payload["reason"] = "operation_on_blocked"
        eid = sink.add("set_apply", payload)
        return (CONFLICT, None, eid)

    base = set(incoming[1]) if incoming[0] == VALUE else set()
    result = (base | set(decl.add)) - set(decl.remove)
    result_sorted = tuple(sorted(result))
    payload = _set_op_payload(node, attr, decl, incoming, False)
    payload["result_status"] = VALUE
    payload["result_values"] = list(result_sorted)
    eid = sink.add("set_apply", payload)
    return (VALUE, result_sorted, eid)


# ---------------------------------------------------------------- 包装系数

def _edge_payload(parent: NodePair, child: NodePair, factor: Fraction) -> dict:
    return {
        "from": [parent[0], parent[1]],
        "to": [child[0], child[1]],
        "factor": frac_str(factor),
    }


def _build_pack(spec: ValidSpec, sink: EvidenceSink) -> Dict[NodePair, State]:
    pack: Dict[NodePair, State] = {}
    for n in spec.order:
        parent_entries = spec.parents[n]
        if not parent_entries:
            eid = sink.add("pack_root", {"node": [n[0], n[1]]})
            pack[n] = (VALUE, Fraction(1, 1), eid)
            continue

        candidates: List[Tuple[Fraction, str]] = []
        conflict_parent_ev: List[str] = []
        for parent, edge_factor in parent_entries:
            ps = pack[parent]
            if ps[0] == CONFLICT:
                conflict_parent_ev.append(ps[2])
                continue
            total = ps[1] * edge_factor
            join_ev = sink.add("pack_join", {
                "incoming": ps[2],
                "edge": _edge_payload(parent, n, edge_factor),
                "factor": frac_str(total),
            })
            candidates.append((total, join_ev))

        if conflict_parent_ev:
            # 父包装冲突只向本支传播，不影响其他根下的节点
            eid = sink.add("pack_conflict", {
                "alternatives": [ev for _, ev in candidates] + conflict_parent_ev,
                "reason": "parent_pack_conflict",
            })
            pack[n] = (CONFLICT, None, eid)
            continue

        distinct = {f for f, _ in candidates}
        if len(distinct) == 1:
            if len(candidates) == 1:
                f, ev = candidates[0]
            else:
                f = candidates[0][0]
                ev = sink.add("pack_merge", {
                    "alternatives": [ev for _, ev in candidates],
                    "factor": frac_str(f),
                })
            pack[n] = (VALUE, f, ev)
        else:
            eid = sink.add("pack_conflict", {
                "alternatives": [ev for _, ev in candidates],
                "factors": [frac_str(f) for f, _ in candidates],
                "reason": "path_factor_mismatch",
            })
            pack[n] = (CONFLICT, None, eid)
    return pack


# ---------------------------------------------------------------- 主流程

def build_catalog(spec: dict, db_path: str = ":memory:") -> CatalogStore:
    """输入检查 -> 拓扑构建 -> 落盘，返回可读取/解释的 CatalogStore。

    结构错误（未知父、环、坏有理数、坏声明）抛 StructuralError，整次失败。
    """
    validated = validate_spec(spec)
    sink = EvidenceSink()

    attr_states: Dict[NodePair, Dict[str, State]] = {}
    attr_status_counts: Dict[str, int] = {}
    for n in validated.order:
        node_states: Dict[str, State] = {}
        for attr, kind in validated.attributes.items():
            parent_states = [
                attr_states[p][attr]
                for p, _ in validated.parents[n]
                if attr in attr_states[p]
            ]
            decl = validated.declarations[n].get(attr)
            if kind == "single":
                incoming = _combine_single(attr, parent_states, sink)
                state = _apply_single_local(n, attr, decl, incoming, sink)
            else:
                incoming = _combine_set(attr, parent_states, sink)
                state = _apply_set_local(n, attr, decl, incoming, sink)
            if state[0] != ABSENT:
                node_states[attr] = state
            attr_status_counts[state[0]] = attr_status_counts.get(state[0], 0) + 1
        attr_states[n] = node_states

    pack_states = _build_pack(validated, sink)
    pack_status_counts: Dict[str, int] = {}
    for st in pack_states.values():
        pack_status_counts[st[0]] = pack_status_counts.get(st[0], 0) + 1

    store = CatalogStore(db_path)
    store.populate(
        spec=validated,
        attr_states=attr_states,
        pack_states=pack_states,
        evidence=sink,
        attr_status_counts=attr_status_counts,
        pack_status_counts=pack_status_counts,
    )
    return store
