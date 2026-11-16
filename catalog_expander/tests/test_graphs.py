"""独立枚举器交叉核对、深菱形、多根/共享子节点、十万节点材料测试。"""
import os
import random
import time
import unittest
from fractions import Fraction

from catalog import build_catalog, CatalogStore
from catalog.enumerator import enumerate_reference
from catalog.model import NodeRef
from catalog.model import ABSENT, BLOCKED, CONFLICT, VALUE
from catalog.rational import frac_str
from tests.helpers import (
    block, edge, node, set_block, set_inherit, set_reset, single, spec,
)


def build_rich_small_graph():
    """覆盖同值多来源、block+值、冲突、reset、remove 再 add、菱形包装。"""
    attrs = {"brand": "single", "color": "single", "tags": "set"}
    nodes = [
        node("ch", "r1", {"brand": single("Acme"), "color": single("red"),
                          "tags": set_reset(("a", "b"))}),
        node("ch", "r2", {"brand": single("Acme"), "color": single("blue"),
                          "tags": set_reset(("b", "c"))}),
        node("ch", "r3", {"color": block(),
                          "tags": set_block()}),
        node("ch", "m1"),
        node("ch", "m2", {"tags": set_inherit(remove=("b",))}),
        node("ch", "leaf", {"color": single("green"),
                            "tags": set_inherit(add=("b",))}),
        node("ch", "other", {"brand": single("Beta")}),
    ]
    edges = [
        edge(("ch", "r1"), ("ch", "m1"), 2),
        edge(("ch", "r2"), ("ch", "m1"), 2),
        edge(("ch", "r2"), ("ch", "m2"), 3),
        edge(("ch", "r3"), ("ch", "m2"), 3),
        edge(("ch", "m1"), ("ch", "leaf"), 3),
        edge(("ch", "m2"), ("ch", "leaf"), 2),
        edge(("ch", "other"), ("ch", "leaf"), 6),
    ]
    return spec(attrs, nodes, edges)


class EnumeratorCrossCheckTest(unittest.TestCase):
    def test_matches_path_enumerator(self):
        input_spec = build_rich_small_graph()
        store = build_catalog(input_spec)
        expected = enumerate_reference(input_spec)
        for (ch, nid), exp in expected.items():
            ref = NodeRef(ch, nid)
            for attr, (status, value) in exp["attrs"].items():
                got = store.get_attr_state(ref, attr)
                self.assertEqual(got.status, status,
                                 f"{nid}.{attr} 状态不一致")
                if status == VALUE:
                    if got.kind == "set":
                        self.assertEqual(list(got.value), list(value))
                    else:
                        self.assertEqual(got.value, value)
            pack = store.get_pack_state(ref)
            exp_status, exp_factor = exp["pack"]
            self.assertEqual(pack.status, exp_status, f"{nid} 包装状态不一致")
            if exp_status == VALUE:
                self.assertEqual(pack.factor, exp_factor)

    def test_handwritten_leaf_expectations(self):
        # 与枚举器独立的手写关键预期
        input_spec = build_rich_small_graph()
        store = build_catalog(input_spec)
        leaf = NodeRef("ch", "leaf")
        # color：m1 上 red/blue conflict（r3 不在 m1 祖先里），leaf 本地 green
        self.assertEqual(store.get_attr_state(leaf, "color").value, "green")
        # brand：r1/r2 同值 Acme 经 m1 合并；other=Beta 经第三路径 -> conflict
        self.assertEqual(
            store.get_attr_state(leaf, "brand").status, CONFLICT
        )
        # tags 演化：
        # m1 = {a,b,c}（r1/r2 并集）
        # m2: r2 {b,c} 与 r3 blocked 并存 -> conflict
        # leaf 继承 m1 value + m2 conflict -> conflict，本地 add(b) 不能救
        self.assertEqual(
            store.get_attr_state(leaf, "tags").status, CONFLICT
        )
        m1 = NodeRef("ch", "m1")
        self.assertEqual(
            list(store.get_attr_state(m1, "tags").value), ["a", "b", "c"]
        )
        # 包装：r1->m1(2)->leaf(3)=6；r2->m1(2)->leaf(3)=6；
        #      r2->m2(3)->leaf(2)=6；r3->m2(3)->leaf(2)=6；
        #      other->leaf(6)=6 —— 六条路径全为 6，不枚举也不相加
        self.assertEqual(frac_str(store.get_pack_state(leaf).factor), "6")
        # r2->m2 与 r3->m2 两条路径系数都是 3，相等 -> value（无包装冲突）
        m2 = NodeRef("ch", "m2")
        m2_pack = store.get_pack_state(m2)
        self.assertEqual(m2_pack.status, VALUE)
        self.assertEqual(frac_str(m2_pack.factor), "3")


class SharedChildAndMultiRootTest(unittest.TestCase):
    def test_shared_child_computed_once(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("ch", "r1", {"c": single("v")}),
             node("ch", "r2", {"c": single("v")}),
             node("ch", "shared"),
             node("ch", "l1"), node("ch", "l2")],
            [edge(("ch", "r1"), ("ch", "shared")),
             edge(("ch", "r2"), ("ch", "shared")),
             edge(("ch", "shared"), ("ch", "l1")),
             edge(("ch", "shared"), ("ch", "l2"))],
        ))
        for leaf in ("l1", "l2"):
            st = s.get_attr_state(NodeRef("ch", leaf), "c")
            self.assertEqual(st.status, VALUE)
            self.assertEqual(st.value, "v")
        # 两个叶复用同一证据 id（共享子图不复制来源）
        e1 = s.get_attr_state(NodeRef("ch", "l1"), "c").evidence_id
        e2 = s.get_attr_state(NodeRef("ch", "l2"), "c").evidence_id
        self.assertEqual(e1, e2)

    def test_multi_roots_and_channel_identity(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("chA", "x", {"c": single("a")}),
             node("chB", "x", {"c": single("b")}),
             node("chA", "leaf")],
            [edge(("chA", "x"), ("chA", "leaf"))],
        ))
        # 同 node_id 不同 channel 是不同节点；chB: x 与 chA: leaf 无关
        self.assertEqual(
            s.get_attr_state(NodeRef("chA", "leaf"), "c").value, "a"
        )
        self.assertEqual(
            s.get_attr_state(NodeRef("chB", "x"), "c").value, "b"
        )
        self.assertEqual(len(s.list_roots()), 2)


class DeepDiamondTest(unittest.TestCase):
    def test_deep_diamond_no_path_explosion(self):
        # 每层 2 节点、全连接到下一层 -> 路径数 2^depth，
        # 正式实现只做逐层合并，证据数与节点数同阶。
        depth = 14
        layers = [[f"l{i}_0", f"l{i}_1"] for i in range(depth)]
        nodes = [node("d", layers[0][0], {"c": single("v0")}),
                 node("d", layers[0][1], {"c": single("v1")})]
        for i in range(1, depth):
            nodes += [node("d", layers[i][0]), node("d", layers[i][1])]
        edges_ = []
        for i in range(depth - 1):
            for a in layers[i]:
                for b in layers[i + 1]:
                    # 分子分母相等 -> 恒等系数 1，逐层乘积保持 1
                    n = 2 ** i
                    edges_.append(edge(("d", a), ("d", b), f"{n}/{n}"))
        s = build_catalog(spec({"c": "single"}, nodes, edges_))
        last = layers[-1]
        for nid in last:
            # v0/v1 从第一层起冲突，之后一路传播
            self.assertEqual(
                s.get_attr_state(NodeRef("d", nid), "c").status, CONFLICT
            )
            self.assertEqual(
                s.get_pack_state(NodeRef("d", nid)).status, VALUE
            )
        stats = s.stats()
        # 证据数必须随节点数线性，而不是 2^14 条路径
        self.assertLess(stats["evidence_count"], stats["node_count"] * 8)

    def test_deep_diamond_matches_enumerator_small(self):
        depth = 6  # 2^5=32 条路径，枚举器仍可承受
        layers = [[f"l{i}_0", f"l{i}_1"] for i in range(depth)]
        nodes = [node("d", layers[0][0], {"t": set_reset(("a",))}),
                 node("d", layers[0][1], {"t": set_reset(("b",))})]
        for i in range(1, depth):
            nodes += [
                node("d", layers[i][0]),
                node("d", layers[i][1],
                     {"t": set_inherit(add=(f"k{i}",))} if i % 2 else None),
            ]
        edges_ = [
            edge(("d", a), ("d", b))
            for i in range(depth - 1)
            for a in layers[i] for b in layers[i + 1]
        ]
        input_spec = spec({"t": "set"}, nodes, edges_)
        s = build_catalog(input_spec)
        expected = enumerate_reference(input_spec)
        for (ch, nid), exp in expected.items():
            got = s.get_attr_state(NodeRef(ch, nid), "t")
            status, value = exp["attrs"]["t"]
            self.assertEqual(got.status, status, f"{nid} 状态不符")
            if status == VALUE:
                self.assertEqual(list(got.value), list(value))


class LargeMaterialTest(unittest.TestCase):
    def test_hundred_thousand_nodes_on_disk(self):
        # 分层 DAG：每层 width 节点，每个节点连下一层两个节点；
        # 路径指数增长，但逐层合并为线性工作。落盘到临时 SQLite 文件。
        import tempfile

        width = 200
        layers = 500  # 100,000 节点
        rng = random.Random(42)
        nodes, edges_ = [], []
        for i in range(layers):
            for j in range(width):
                nid = f"n{i}_{j}"
                decls = None
                if i == 0:
                    decls = {"brand": single("Acme"),
                             "tags": set_reset(("x", "y"))}
                elif j == 0 and i % 50 == 0:
                    decls = {"tags": set_inherit(add=("z",))}
                nodes.append(node("big", nid, decls))
        for i in range(layers - 1):
            for j in range(width):
                for k in (j, (j + 1) % width):
                    edges_.append(
                        edge(("big", f"n{i}_{j}"),
                             ("big", f"n{i + 1}_{k}"),
                             rng.choice([1, 2, "1/2", "2/1"]))
                    )
        input_spec = spec(
            {"brand": "single", "tags": "set"}, nodes, edges_
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "catalog.db")
            t0 = time.time()
            store = build_catalog(input_spec, db_path=db)
            elapsed = time.time() - t0
            stats = store.stats()
            self.assertEqual(stats["node_count"], 100_000)
            self.assertEqual(stats["edge_count"],
                             (layers - 1) * width * 2)
            # brand 全图同值，所有节点都应是 value=Acme（无冲突扩散）
            sample_leaf = NodeRef("big", f"n{layers - 1}_7")
            brand = store.get_attr_state(sample_leaf, "brand")
            self.assertEqual(brand.status, VALUE)
            self.assertEqual(brand.value, "Acme")
            tags = store.get_attr_state(sample_leaf, "tags")
            self.assertIn(tags.status, (VALUE, CONFLICT))
            # 证据节点数随图规模线性，与路径数无关
            self.assertLess(stats["evidence_count"],
                            stats["node_count"] * 4)
            # 叶读取与解释入口在落盘库上可用
            leaf_result = store.read_leaf(sample_leaf)
            self.assertEqual(set(leaf_result.attributes), {"brand", "tags"})
            explanation = store.explain_attr(sample_leaf, "brand")
            self.assertEqual(explanation["status"], VALUE)
            # 重新打开同一库仍可读取
            store.close()
            reopened = CatalogStore.open_existing(db)
            self.assertEqual(
                reopened.get_attr_state(sample_leaf, "brand").value, "Acme"
            )
            self.assertEqual(reopened.stats()["node_count"], 100_000)
            reopened.close()
        # 线性时间上界（宽松）：十万节点应在数十秒内完成
        self.assertLess(elapsed, 120)


if __name__ == "__main__":
    unittest.main()
