"""主演练 R1/R2/L + 包装菱形 + set 演化，全部为手写预期。"""
import unittest
from fractions import Fraction

from catalog import build_catalog
from catalog.model import ABSENT, BLOCKED, CONFLICT, VALUE, NodeRef
from catalog.rational import frac_str
from tests.helpers import (
    block, edge, inherit, node, set_block, set_inherit, set_reset, single, spec,
)

CH = "c1"
R1, R2, L, D, M, X = ((CH, "R1"), (CH, "R2"), (CH, "L"),
                      (CH, "D"), (CH, "M"), (CH, "X"))


def build_main_walkthrough():
    # 属性菱形（L 是 R1/R2 的共享子节点）：
    #   R1 --2--> L          R2 --6--> L      -> L 包装 conflict(2 vs 6)
    # 包装菱形（D 的两条根路径独立、系数相等）：
    #   R1 --2--> X --3--> D （2x3=6）        R2 --6--> D   -> D 包装 value 6
    # set 演化：R1/R2 并集后 L 移除 y，D 再 add y 回来
    # M：与 L 两条路径系数相等（8 与 6 经各自边），见下方边定义
    attrs = {
        "brand": "single",
        "color": "single",
        "size": "single",
        "sales_pack": "set",
        "tags": "set",
    }
    nodes = [
        node(*R1, {
            "brand": single("Acme"),
            "color": single("red"),
            "sales_pack": set_reset(("x", "y")),
        }),
        node(*R2, {
            "brand": single("Acme"),           # 与 R1 同值 -> 合并证据
            "color": single("blue"),
            "sales_pack": set_reset(("y", "z")),
        }),
        node(*L, {
            "color": single("green"),          # 显式覆盖 red/blue 冲突
            "sales_pack": set_inherit(remove=("y",)),  # 并集{x,y,z}-y={x,z}
        }),
        node(*X),
        node(*D, {
            "size": single("M"),               # 尺码变体覆盖尺码
            "sales_pack": set_inherit(add=("y",)),     # {x,z}+y={x,y,z}
        }),
        node(*M, {"tags": set_reset(("q",))}),
    ]
    edges = [
        edge(R1, L, 2),
        edge(R2, L, 6),
        edge(R1, X, 2),
        edge(X, D, 3),
        edge(R2, D, 6),
        edge(L, M, 1),
        edge(R2, M, 2),
    ]
    return build_catalog(spec(attrs, nodes, edges))


class MainWalkthroughTest(unittest.TestCase):
    def setUp(self):
        self.store = build_main_walkthrough()

    def test_leaf_set(self):
        leaves = {n.as_pair() for n in self.store.list_leaves()}
        self.assertEqual(leaves, {D, M})  # L 有出边到 M，不是叶

    def test_color_conflict_then_override_green(self):
        # 覆盖前的冲突必须能在解释中找到被保留的双方来源
        exp = self.store.explain_attr(NodeRef(*L), "color")
        self.assertEqual(exp["status"], VALUE)
        self.assertEqual(exp["value"], "green")
        root = exp["evidence"]
        self.assertEqual(root["kind"], "single_override")
        # incoming 指向 red/blue 的 single_merge 冲突证据
        incoming = root["refs"]["incoming"]
        self.assertEqual(incoming["kind"], "single_merge")
        self.assertEqual(incoming["payload"]["result_status"], CONFLICT)
        # 原声明必须同时包含被覆盖的 red/blue 与本地 green
        prim_values = {
            p["payload"].get("value")
            for p in exp["primitives"]
            if p["kind"] == "prim_single"
        }
        self.assertEqual(prim_values, {"red", "blue", "green"})

    def test_brand_same_value_merged(self):
        st = self.store.get_attr_state(NodeRef(*L), "brand")
        self.assertEqual(st.status, VALUE)
        self.assertEqual(st.value, "Acme")
        exp = self.store.explain_attr(NodeRef(*L), "brand")
        self.assertEqual(exp["evidence"]["kind"], "single_merge")
        self.assertEqual(len(exp["evidence"]["payload"]["sources"]), 2)

    def test_set_remove_then_descendant_add(self):
        l_pack = self.store.get_attr_state(NodeRef(*L), "sales_pack")
        self.assertEqual(l_pack.status, VALUE)
        self.assertEqual(list(l_pack.value), ["x", "z"])  # 移除 y
        d_pack = self.store.get_attr_state(NodeRef(*D), "sales_pack")
        # D 的祖先 X/R1/R2：R1/R2 并集 {x,y,z}，D 本地 add(y) 不改变并集
        self.assertEqual(list(d_pack.value), ["x", "y", "z"])
        # remove 不是黑名单的独立小图：remove 后后代再 add 必回来
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r", {"t": set_reset(("x", "y"))}),
             node("c", "a", {"t": set_inherit(remove=("y",))}),
             node("c", "b", {"t": set_inherit(add=("y",))})],
            [edge(("c", "r"), ("c", "a")), edge(("c", "a"), ("c", "b"))],
        ))
        self.assertEqual(
            list(s.get_attr_state(NodeRef("c", "a"), "t").value), ["x"]
        )
        self.assertEqual(
            list(s.get_attr_state(NodeRef("c", "b"), "t").value),
            ["x", "y"],
        )

    def test_size_local_on_leaf(self):
        st = self.store.get_attr_state(NodeRef(*D), "size")
        self.assertEqual(st.status, VALUE)
        self.assertEqual(st.value, "M")

    def test_absent_propagation_and_distinction(self):
        # size 在根/L 上从未声明 -> absent，且没有证据节点
        st = self.store.get_attr_state(NodeRef(*R1), "size")
        self.assertEqual(st.status, ABSENT)
        self.assertIsNone(st.evidence_id)
        # 空集合属于 value 而不是 absent：reset 空集后再 add
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "a", {"t": set_reset([])}),
             node("c", "b", {"t": set_inherit(add=("k",))})],
            [edge(("c", "a"), ("c", "b"))],
        ))
        a = s.get_attr_state(NodeRef("c", "a"), "t")
        self.assertEqual(a.status, VALUE)
        self.assertEqual(list(a.value), [])
        b = s.get_attr_state(NodeRef("c", "b"), "t")
        self.assertEqual(list(b.value), ["k"])

    def test_pack_diamond_equal_factors_six(self):
        # R1->X(2)->D(3) = 6；R2->D(6) = 6；两条路径不相交也不相加
        d = self.store.get_pack_state(NodeRef(*D))
        self.assertEqual(d.status, VALUE)
        self.assertEqual(frac_str(d.factor), "6")
        exp = self.store.explain_pack(NodeRef(*D))
        # 解释中两条路径涉及的边都能展开，且不复制全图
        edge_keys = {(tuple(e["from"]), tuple(e["to"])) for e in exp["edges"]}
        self.assertIn((R1, X), edge_keys)
        self.assertIn((X, D), edge_keys)
        self.assertIn((R2, D), edge_keys)

    def test_pack_conflict_does_not_erase_brand(self):
        # L 经两条路径得 2 与 6 -> 包装 conflict
        l = self.store.get_pack_state(NodeRef(*L))
        self.assertEqual(l.status, CONFLICT)
        # 但 L 上已唯一确定的品牌/颜色不受影响
        leaf_l = self.store.read_leaf(NodeRef(*L))
        self.assertEqual(leaf_l.attributes["brand"].status, VALUE)
        self.assertEqual(leaf_l.attributes["color"].status, VALUE)
        self.assertEqual(leaf_l.pack.status, CONFLICT)

    def test_pack_conflict_only_when_factor_changes(self):
        # 把一条边改为 8：仅包装冲突，同值属性仍是 value
        s = build_catalog(spec(
            {"color": "single"},
            [node(*R1, {"color": single("red")}),
             node(*R2, {"color": single("red")}),
             node(*L)],
            [edge(R1, L, 2), edge(R2, L, 8)],
        ))
        l = s.get_pack_state(NodeRef(*L))
        self.assertEqual(l.status, CONFLICT)
        color = s.get_attr_state(NodeRef(*L), "color")
        self.assertEqual(color.status, VALUE)
        self.assertEqual(color.value, "red")
        exp = s.explain_pack(NodeRef(*L))
        factors = sorted(
            alt["payload"]["factor"]
            for alt in exp["evidence"]["refs"]["alternatives"]
        )
        self.assertEqual(factors, ["2", "8"])

    def test_pack_conflict_propagates_only_down_dependent_branch(self):
        # M 的父之一是包装冲突的 L（边系数 1），另一路 R2(1)->M(2)=2；
        # L 支系没有唯一系数 -> M 包装 conflict；独立节点 D 仍为 value 6
        self.assertEqual(
            self.store.get_pack_state(NodeRef(*M)).status, CONFLICT
        )
        self.assertEqual(
            self.store.get_pack_state(NodeRef(*D)).status, VALUE
        )

    def test_root_pack_is_one(self):
        r1 = self.store.get_pack_state(NodeRef(*R1))
        self.assertEqual(r1.status, VALUE)
        self.assertEqual(r1.factor, Fraction(1, 1))

    def test_stats_recorded(self):
        stats = self.store.stats()
        self.assertEqual(stats["node_count"], 6)
        self.assertEqual(stats["edge_count"], 7)
        self.assertGreater(stats["evidence_count"], 0)
        self.assertEqual(stats["leaf_count"], 2)
        self.assertGreaterEqual(stats["pack_conflict"], 2)

    def test_evidence_is_shared_not_per_leaf_copied(self):
        # D 与 M 不共享祖先声明路径；但同内容原声明在全库内容寻址去重
        d_brand = self.store.get_attr_state(NodeRef(*D), "brand")
        self.assertEqual(d_brand.status, VALUE)
        self.assertEqual(
            self.store.read_leaf(NodeRef(*M)).attributes["tags"].value,
            ("q",),
        )


if __name__ == "__main__":
    unittest.main()
