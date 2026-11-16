"""SQLite 存储与读取/解释入口。

表设计避免任何路径复制：
  nodes / edges 存图；
  attr_states / pack_states 只引用共享证据节点 id；
  evidence 存证据图（合并/覆盖/操作/原声明/边连接/包装）。
"""
import os
import sqlite3
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from .errors import StructuralError
from .model import ABSENT, BLOCKED, CONFLICT, VALUE, AttrState, LeafResult, NodeRef, PackState
from .rational import frac_str
from .validator import ValidSpec

NodePair = Tuple[str, str]

# 各证据 kind 中指向其他证据 id 的负载字段
_REF_KEYS = ("sources", "incoming", "alternatives", "local")


class CatalogStore:
    """构建结果的持久化句柄，也是所有读取/解释入口。"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        # 打开既有文件库时不重建表（内存库总是新建）
        existing = (
            db_path != ":memory:"
            and os.path.exists(db_path)
            and os.path.getsize(db_path) > 0
        )
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        if not existing:
            self._create_schema()
        self._spec: Optional[ValidSpec] = None
        self._node_pairs: List[NodePair] = []
        self._attr_schema: Dict[str, str] = {}

    @classmethod
    def open_existing(cls, db_path: str) -> "CatalogStore":
        """打开已落盘的目录库并恢复读取所需索引。"""
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            raise StructuralError(f"目录库不存在或为空: {db_path}")
        store = cls(db_path)
        store._ensure_loaded()
        return store

    # ------------------------------------------------------------ 建表/落盘

    def _create_schema(self):
        cur = self.conn.executescript(
            """
            CREATE TABLE nodes(
                channel TEXT NOT NULL, node_id TEXT NOT NULL,
                ord_idx INTEGER NOT NULL,
                PRIMARY KEY(channel, node_id)
            );
            CREATE TABLE edges(
                parent_channel TEXT NOT NULL, parent_node_id TEXT NOT NULL,
                child_channel TEXT NOT NULL, child_node_id TEXT NOT NULL,
                factor_num INTEGER NOT NULL, factor_den INTEGER NOT NULL,
                factor_text TEXT NOT NULL,
                PRIMARY KEY(parent_channel, parent_node_id,
                            child_channel, child_node_id)
            );
            CREATE TABLE attributes(
                attr TEXT PRIMARY KEY, kind TEXT NOT NULL
            );
            CREATE TABLE attr_states(
                channel TEXT NOT NULL, node_id TEXT NOT NULL,
                attr TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL,
                value_json TEXT,
                evidence_id TEXT,
                PRIMARY KEY(channel, node_id, attr)
            );
            CREATE TABLE pack_states(
                channel TEXT NOT NULL, node_id TEXT NOT NULL,
                status TEXT NOT NULL,
                factor_num INTEGER, factor_den INTEGER,
                evidence_id TEXT,
                PRIMARY KEY(channel, node_id)
            );
            CREATE TABLE evidence(
                evidence_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )

    def populate(self, spec: ValidSpec,
                 attr_states: Dict[NodePair, Dict[str, Tuple]],
                 pack_states: Dict[NodePair, Tuple],
                 evidence,
                 attr_status_counts: Dict[str, int],
                 pack_status_counts: Dict[str, int]):
        import json

        self._spec = spec
        self._node_pairs = list(spec.nodes)
        self._attr_schema = dict(spec.attributes)
        cur = self.conn.cursor()
        cur.executemany(
            "INSERT INTO nodes(channel, node_id, ord_idx) VALUES(?,?,?)",
            [(ch, nid, idx) for idx, (ch, nid) in enumerate(spec.nodes)],
        )
        cur.executemany(
            "INSERT INTO attributes(attr, kind) VALUES(?,?)",
            list(spec.attributes.items()),
        )
        cur.executemany(
            """INSERT INTO edges(parent_channel, parent_node_id,
                   child_channel, child_node_id,
                   factor_num, factor_den, factor_text)
               VALUES(?,?,?,?,?,?,?)""",
            [
                (p[0], p[1], c[0], c[1],
                 f.numerator, f.denominator, frac_str(f))
                for (p, c, f) in spec.edges
            ],
        )
        attr_rows = []
        for (ch, nid), states in attr_states.items():
            for attr, (status, value, eid) in states.items():
                kind = spec.attributes[attr]
                value_json = None
                if status == VALUE:
                    value_json = json.dumps(
                        list(value) if kind == "set" else value,
                        ensure_ascii=False,
                    )
                attr_rows.append(
                    (ch, nid, attr, kind, status, value_json, eid)
                )
        cur.executemany(
            """INSERT INTO attr_states(channel, node_id, attr, kind,
                   status, value_json, evidence_id)
               VALUES(?,?,?,?,?,?,?)""",
            attr_rows,
        )
        cur.executemany(
            """INSERT INTO pack_states(channel, node_id, status,
                   factor_num, factor_den, evidence_id)
               VALUES(?,?,?,?,?,?)""",
            [
                (ch, nid, st[0],
                 st[1].numerator if st[1] is not None else None,
                 st[1].denominator if st[1] is not None else None,
                 st[2])
                for (ch, nid), st in pack_states.items()
            ],
        )
        cur.executemany(
            "INSERT INTO evidence(evidence_id, kind, payload_json) VALUES(?,?,?)",
            [(eid, node["kind"], json.dumps(node["payload"], ensure_ascii=False))
             for eid, node in evidence.nodes.items()],
        )
        meta = {
            "node_count": len(spec.nodes),
            "edge_count": len(spec.edges),
            "evidence_count": len(evidence.nodes),
            "leaf_count": sum(1 for n in spec.nodes if not spec.children[n]),
            "root_count": sum(1 for n in spec.nodes if not spec.parents[n]),
            "attr_value": attr_status_counts.get(VALUE, 0),
            "attr_absent": attr_status_counts.get(ABSENT, 0),
            "attr_blocked": attr_status_counts.get(BLOCKED, 0),
            "attr_conflict": attr_status_counts.get(CONFLICT, 0),
            "pack_value": pack_status_counts.get(VALUE, 0),
            "pack_conflict": pack_status_counts.get(CONFLICT, 0),
        }
        cur.executemany(
            "INSERT INTO meta(key, value) VALUES(?,?)",
            [(k, str(v)) for k, v in meta.items()],
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ 基础读取

    @staticmethod
    def _pair(row) -> NodePair:
        return (row["channel"], row["node_id"])

    def _ensure_loaded(self):
        """打开既有库时从表中恢复最小内存索引。"""
        if self._spec is not None:
            return
        rows = self.conn.execute(
            "SELECT channel, node_id FROM nodes ORDER BY ord_idx"
        ).fetchall()
        self._node_pairs = [(r["channel"], r["node_id"]) for r in rows]
        self._attr_schema = {
            r["attr"]: r["kind"]
            for r in self.conn.execute("SELECT attr, kind FROM attributes")
        }
        parents: Dict[NodePair, List[NodePair]] = {}
        children: Dict[NodePair, List[NodePair]] = {n: [] for n in self._node_pairs}
        for r in self.conn.execute(
            """SELECT parent_channel pc, parent_node_id pn,
                      child_channel cc, child_node_id cn FROM edges"""
        ):
            p, c = (r["pc"], r["pn"]), (r["cc"], r["cn"])
            children.setdefault(p, []).append(c)
            parents.setdefault(c, []).append(p)
        from .validator import ValidSpec

        self._spec = ValidSpec(
            attributes=self._attr_schema,
            nodes=self._node_pairs,
            node_index={n: i for i, n in enumerate(self._node_pairs)},
            declarations={}, parents=parents, children=children,
            edges=[], order=self._node_pairs, raw={},
        )

    def list_leaves(self) -> List[NodeRef]:
        """所有可售叶节点（无子边的节点），按拓扑序。"""
        self._ensure_loaded()
        leaf_set = {n for n in self._node_pairs
                    if not self._spec.children.get(n)}
        return [NodeRef.of(n) for n in self._node_pairs if n in leaf_set]

    def list_roots(self) -> List[NodeRef]:
        self._ensure_loaded()
        root_set = {n for n in self._node_pairs
                    if not self._spec.parents.get(n)}
        return [NodeRef.of(n) for n in self._node_pairs if n in root_set]

    def get_attr_state(self, node: NodeRef, attr: str) -> AttrState:
        import json

        row = self.conn.execute(
            "SELECT * FROM attr_states WHERE channel=? AND node_id=? AND attr=?",
            (node.channel, node.node_id, attr),
        ).fetchone()
        if row is None:
            return AttrState(attr=attr, kind=self._attr_schema[attr],
                             status=ABSENT, value=None, evidence_id=None)
        value = None
        if row["status"] == VALUE:
            parsed = json.loads(row["value_json"])
            value = tuple(parsed) if row["kind"] == "set" else parsed
        return AttrState(
            attr=attr, kind=row["kind"], status=row["status"],
            value=value, evidence_id=row["evidence_id"],
        )

    def get_pack_state(self, node: NodeRef) -> PackState:
        row = self.conn.execute(
            "SELECT * FROM pack_states WHERE channel=? AND node_id=?",
            (node.channel, node.node_id),
        ).fetchone()
        if row is None:
            raise StructuralError(f"未知节点 {node}")
        factor = None
        if row["factor_num"] is not None:
            factor = Fraction(row["factor_num"], row["factor_den"])
        return PackState(status=row["status"], factor=factor,
                         evidence_id=row["evidence_id"])

    def read_leaf(self, node: NodeRef) -> LeafResult:
        """逐属性状态 + 包装结果的叶节点读取入口。"""
        self._ensure_loaded()
        attributes = {
            attr: self.get_attr_state(node, attr)
            for attr in self._attr_schema
        }
        return LeafResult(node=node, attributes=attributes,
                          pack=self.get_pack_state(node))

    def iter_leaves(self):
        for ref in self.list_leaves():
            yield self.read_leaf(ref)

    # ------------------------------------------------------------ 证据解释

    def _evidence_row(self, evidence_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise StructuralError(f"证据节点不存在: {evidence_id}")
        return row

    def _load_evidence_payloads(self, evidence_id: str):
        """迭代收集证据闭包：返回 (视图表, 根视图)。

        沿 sources/incoming/alternatives/local 引用做显式栈遍历，
        深度再大也不会递归爆栈；共享证据只展开一次，再次出现标记 shared。
        """
        import json

        memo: Dict[str, dict] = {}
        root_view: Optional[dict] = None
        stack = [evidence_id]
        while stack:
            eid = stack.pop()
            if eid in memo:
                continue
            row = self._evidence_row(eid)
            payload = json.loads(row["payload_json"])
            view = {
                "evidence_id": eid,
                "kind": row["kind"],
                "payload": payload,
                "refs": {},
            }
            memo[eid] = view
            if root_view is None:
                root_view = view
            for key in _REF_KEYS:
                if key not in payload or payload[key] is None:
                    continue
                refs = payload[key]
                if isinstance(refs, str):
                    stack.append(refs)
                else:
                    stack.extend(refs)
        # 第二遍：按 memo 中已物化的视图连边；统计每个目标被多少父引用，
        # 被多个父引用的共享证据在第二及以后的引用处标记 shared。
        incoming_count: Dict[str, int] = {}
        for view in memo.values():
            for key in _REF_KEYS:
                payload = view["payload"]
                if key not in payload or payload[key] is None:
                    continue
                refs = payload[key]
                refs = [refs] if isinstance(refs, str) else refs
                for r in refs:
                    incoming_count[r] = incoming_count.get(r, 0) + 1
        emitted: Dict[str, int] = {}
        for eid, view in memo.items():
            for key in _REF_KEYS:
                payload = view["payload"]
                if key not in payload or payload[key] is None:
                    continue
                refs = payload[key]
                if isinstance(refs, str):
                    view["refs"][key] = self._link_ref(
                        refs, memo, emitted, incoming_count)
                else:
                    view["refs"][key] = [
                        self._link_ref(r, memo, emitted, incoming_count)
                        for r in refs
                    ]
        return memo, root_view

    @staticmethod
    def _link_ref(target: str, memo: Dict[str, dict],
                  emitted: Dict[str, int], incoming_count: Dict[str, int]) -> dict:
        n = emitted.get(target, 0)
        emitted[target] = n + 1
        if n > 0 and incoming_count.get(target, 0) > 1:
            return {"evidence_id": target, "shared": True}
        return memo[target]

    def explain_attr(self, node: NodeRef, attr: str) -> dict:
        """解释某节点某属性的有效状态，展开到具体原声明与边。"""
        state = self.get_attr_state(node, attr)
        out = {
            "node": node.to_json(),
            "attr": attr,
            "kind": state.kind,
            "status": state.status,
        }
        if state.status == VALUE:
            out["value"] = list(state.value) if state.kind == "set" else state.value
        if state.evidence_id is None:
            out["evidence"] = None
            out["primitives"] = []
            return out
        memo, root_view = self._load_evidence_payloads(state.evidence_id)
        out["evidence"] = root_view
        out["primitives"] = self._collect_primitives(memo)
        return out

    def explain_pack(self, node: NodeRef) -> dict:
        """解释包装系数（根=1；多路径不一致给出各路径候选及边）。"""
        state = self.get_pack_state(node)
        memo, root_view = self._load_evidence_payloads(state.evidence_id)
        return {
            "node": node.to_json(),
            "status": state.status,
            "factor": frac_str(state.factor) if state.factor is not None else None,
            "evidence": root_view,
            "edges": self._collect_edges(memo),
            "primitives": self._collect_primitives(memo),
        }

    @staticmethod
    def _collect_primitives(memo: Dict[str, dict]) -> List[dict]:
        """从已展开证据中去重提取原声明（prim_*）。"""
        seen = set()
        out = []
        for eid, view in memo.items():
            if view["kind"].startswith("prim_"):
                if eid not in seen:
                    seen.add(eid)
                    out.append({"evidence_id": eid,
                                "kind": view["kind"],
                                "payload": view["payload"]})
        return out

    @staticmethod
    def _collect_edges(memo: Dict[str, dict]) -> List[dict]:
        """从包装证据中去重提取涉及的边及系数。"""
        seen = set()
        out = []
        for view in memo.values():
            payload = view["payload"]
            if view["kind"] == "pack_join":
                edge = payload["edge"]
                key = (tuple(edge["from"]), tuple(edge["to"]))
                if key not in seen:
                    seen.add(key)
                    out.append(edge)
        return out

    def primitives(self) -> List[dict]:
        """全库原始声明证据（原声明即输入中显式给出的 single/block/reset 等）。"""
        import json

        return [
            {
                "evidence_id": r["evidence_id"],
                "kind": r["kind"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in self.conn.execute(
                "SELECT * FROM evidence WHERE kind LIKE 'prim_%' ORDER BY evidence_id"
            )
        ]

    # ------------------------------------------------------------ 统计

    def stats(self) -> Dict[str, Any]:
        """实际处理的节点/边/证据节点数及状态分布。"""
        rows = self.conn.execute("SELECT key, value FROM meta").fetchall()
        return {r["key"]: int(r["value"]) for r in rows}
