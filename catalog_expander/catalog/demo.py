"""命令行演示：读取输入 JSON，构建目录并打印逐叶结果与解释。

用法：
    python -m catalog.demo input.json [catalog.db]

input.json 形状见 README.md。不传 db 路径时使用内存库。
"""
import json
import sys

from . import build_catalog
from .rational import frac_str


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("用法: python -m catalog.demo input.json [catalog.db]")
        return 2
    with open(argv[0], "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    db_path = argv[1] if len(argv) > 1 else ":memory:"
    store = build_catalog(spec, db_path=db_path)

    for leaf in store.iter_leaves():
        print(f"\n=== 叶节点 {leaf.node.channel}/{leaf.node.node_id} ===")
        for attr, state in sorted(leaf.attributes.items()):
            if state.status == "value":
                shown = list(state.value) if state.kind == "set" else state.value
                print(f"  {attr} [{state.kind}] = value {shown!r}")
            else:
                print(f"  {attr} [{state.kind}] = {state.status}")
        pack = leaf.pack
        if pack.status == "value":
            print(f"  pack_factor = {frac_str(pack.factor)}")
        else:
            print("  pack_factor = conflict（多路径系数不一致）")

    print("\n=== 处理统计 ===")
    for key, value in sorted(store.stats().items()):
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
