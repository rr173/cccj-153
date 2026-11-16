"""结构错误：未知父节点、环、坏有理数、坏声明等均整次失败。"""
import unittest

from catalog import build_catalog, StructuralError
from tests.helpers import edge, node, single, spec


class StructuralErrorTest(unittest.TestCase):
    def _ok_attrs(self):
        return {"c": "single"}

    def test_unknown_parent(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "x")],
                [edge(("c", "ghost"), ("c", "x"))],
            ))

    def test_unknown_child(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "x")],
                [edge(("c", "x"), ("c", "ghost"))],
            ))

    def test_cycle_detected(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "a"), node("c", "b"), node("c", "d")],
                [edge(("c", "a"), ("c", "b")),
                 edge(("c", "b"), ("c", "d")),
                 edge(("c", "d"), ("c", "a"))],
            ))

    def test_self_loop(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "a")],
                [edge(("c", "a"), ("c", "a"))],
            ))

    def test_bad_rationals(self):
        for bad in (0, -2, 1.5, "1.5", "1/0", "abc", True):
            with self.subTest(bad=bad):
                with self.assertRaises(StructuralError):
                    build_catalog(spec(
                        self._ok_attrs(),
                        [node("c", "a"), node("c", "b")],
                        [edge(("c", "a"), ("c", "b"), bad)],
                    ))

    def test_good_rationals_accepted(self):
        for good in (2, "3", "2/3", "7/5"):
            with self.subTest(good=good):
                store = build_catalog(spec(
                    self._ok_attrs(),
                    [node("c", "a"), node("c", "b")],
                    [edge(("c", "a"), ("c", "b"), good)],
                ))
                self.assertEqual(
                    store.get_pack_state(__import__("catalog").model.NodeRef(
                        "c", "b")).status, "value"
                )

    def test_unknown_attribute_rejected(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                {"c": "single"},
                [node("c", "a", {"nope": single("v")})],
                [],
            ))

    def test_wrong_declaration_shape_rejected(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                {"c": "single"},
                [node("c", "a", {"c": {"mode": "weird"}})],
                [],
            ))
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                {"t": "set"},
                [node("c", "a", {"t": {"base": "reset"}})],  # 缺 values
                [],
            ))

    def test_duplicate_node_and_edge_rejected(self):
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "a"), node("c", "a")], [],
            ))
        with self.assertRaises(StructuralError):
            build_catalog(spec(
                self._ok_attrs(),
                [node("c", "a"), node("c", "b")],
                [edge(("c", "a"), ("c", "b")),
                 edge(("c", "a"), ("c", "b"))],
            ))

    def test_forward_reference_accepted(self):
        # 边先引用后面才定义的节点不是错误
        store = build_catalog({
            "attributes": {"c": "single"},
            "nodes": [node("c", "child"),
                      node("c", "parent", {"c": single("v")})],
            "edges": [edge(("c", "parent"), ("c", "child"))],
        })
        self.assertEqual(
            store.get_attr_state(__import__("catalog").model.NodeRef(
                "c", "child"), "c").value,
            "v",
        )

    def test_attribute_conflict_is_not_structural_error(self):
        store = build_catalog(spec(
            {"c": "single"},
            [node("c", "r1", {"c": single("a")}),
             node("c", "r2", {"c": single("b")}),
             node("c", "x")],
            [edge(("c", "r1"), ("c", "x")), edge(("c", "r2"), ("c", "x"))],
        ))
        self.assertEqual(
            store.get_attr_state(__import__("catalog").model.NodeRef(
                "c", "x"), "c").status,
            "conflict",
        )


if __name__ == "__main__":
    unittest.main()
