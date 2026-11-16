"""single/set 继承细语义：block、reset、blocked+操作、全 absent 等。"""
import unittest

from catalog import build_catalog, StructuralError
from catalog.model import NodeRef
from catalog.model import ABSENT, BLOCKED, CONFLICT, VALUE
from tests.helpers import (
    block, edge, inherit, node, set_block, set_inherit, set_reset, single, spec,
)


def st(store, pair, attr):
    return store.get_attr_state(NodeRef(*pair), attr)


class SingleSemanticsTest(unittest.TestCase):
    def test_block_and_value_is_conflict(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("c", "r1", {"c": single("v")}),
             node("c", "r2", {"c": block()}),
             node("c", "x")],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "c").status, CONFLICT)

    def test_conflict_propagates_then_local_block_overrides(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("c", "r1", {"c": single("a")}),
             node("c", "r2", {"c": single("b")}),
             node("c", "x"),
             node("c", "y", {"c": block()})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "x"), ("c", "y"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "c").status, CONFLICT)
        y = st(s, ("c", "y"), "c")
        self.assertEqual(y.status, BLOCKED)
        exp = s.explain_attr(NodeRef("c", "y"), "c")
        self.assertEqual(exp["evidence"]["kind"], "single_override")
        self.assertEqual(exp["evidence"]["payload"]["form"], "block")
        # 被覆盖的冲突仍保留在 incoming 链上
        self.assertEqual(
            exp["evidence"]["refs"]["incoming"]["payload"]["result_status"],
            CONFLICT,
        )

    def test_all_absent_stays_absent_ignored_in_merge(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("c", "r1"), node("c", "r2"),
             node("c", "x", {"c": single("v")})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "c").status, VALUE)
        self.assertEqual(st(s, ("c", "r1"), "c").status, ABSENT)

    def test_all_block_is_blocked(self):
        s = build_catalog(spec(
            {"c": "single"},
            [node("c", "r1", {"c": block()}),
             node("c", "r2", {"c": block()}),
             node("c", "x")],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "c").status, BLOCKED)


class SetSemanticsTest(unittest.TestCase):
    def test_union_then_remove_then_descendant_add(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r1", {"t": set_reset(("x", "y"))}),
             node("c", "r2", {"t": set_reset(("y", "z"))}),
             node("c", "x", {"t": set_inherit(remove=("y",))}),
             node("c", "y", {"t": set_inherit(add=("y",))})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "x"), ("c", "y"))],
        ))
        self.assertEqual(list(st(s, ("c", "x"), "t").value), ["x", "z"])
        # remove 不是黑名单：后代重新 add y 应回来
        self.assertEqual(list(st(s, ("c", "y"), "t").value),
                         ["x", "y", "z"])

    def test_reset_discards_parents_and_overrides_conflict(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r1", {"t": set_reset(("a",))}),
             node("c", "r2", {"t": set_block()}),
             node("c", "x"),  # block + 值 -> conflict
             node("c", "y", {"t": set_reset(("k", "m"))})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "x"), ("c", "y"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "t").status, CONFLICT)
        y = st(s, ("c", "y"), "t")
        self.assertEqual(y.status, VALUE)
        self.assertEqual(list(y.value), ["k", "m"])  # reset 覆盖父冲突

    def test_block_overrides_parent_conflict(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r1", {"t": set_reset(("a",))}),
             node("c", "r2", {"t": set_block()}),
             node("c", "x"),
             node("c", "y", {"t": set_block()})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "x"), ("c", "y"))],
        ))
        self.assertEqual(st(s, ("c", "y"), "t").status, BLOCKED)

    def test_add_remove_cannot_override_conflict(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r1", {"t": set_reset(("a",))}),
             node("c", "r2", {"t": set_block()}),
             node("c", "x"),
             node("c", "y", {"t": set_inherit(add=("q",))})],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "x"), ("c", "y"))],
        ))
        self.assertEqual(st(s, ("c", "y"), "t").status, CONFLICT)

    def test_operation_on_blocked_is_semantic_conflict(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r", {"t": set_block()}),
             node("c", "x", {"t": set_inherit(add=("q",))})],
            [edge(("c", "r"), ("c", "x"))],
        ))
        x = st(s, ("c", "x"), "t")
        self.assertEqual(x.status, CONFLICT)
        exp = s.explain_attr(NodeRef("c", "x"), "t")
        self.assertEqual(exp["evidence"]["payload"]["reason"],
                         "operation_on_blocked")

    def test_inherit_on_blocked_stays_blocked(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r", {"t": set_block()}),
             node("c", "x", {"t": set_inherit()})],
            [edge(("c", "r"), ("c", "x"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "t").status, BLOCKED)

    def test_all_blocked_is_blocked_all_absent_is_absent(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r1", {"t": set_block()}),
             node("c", "r2", {"t": set_block()}),
             node("c", "x"),
             node("c", "a1"), node("c", "a2"),
             node("c", "z")],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x")),
             edge(("c", "a1"), ("c", "z")), edge(("c", "a2"), ("c", "z"))],
        ))
        self.assertEqual(st(s, ("c", "x"), "t").status, BLOCKED)
        z = st(s, ("c", "z"), "t")
        self.assertEqual(z.status, ABSENT)
        self.assertIsNone(z.evidence_id)

    def test_empty_set_is_value_not_absent(self):
        s = build_catalog(spec(
            {"t": "set"},
            [node("c", "r", {"t": set_reset(("a",))}),
             node("c", "x", {"t": set_inherit(remove=("a",))})],
            [edge(("c", "r"), ("c", "x"))],
        ))
        x = st(s, ("c", "x"), "t")
        self.assertEqual(x.status, VALUE)
        self.assertEqual(list(x.value), [])

    def test_add_remove_overlap_rejected(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                {"t": "set"},
                [node("c", "r", {"t": set_inherit(add=("a",), remove=("a",))})],
                [],
            ))


if __name__ == "__main__":
    unittest.main()
