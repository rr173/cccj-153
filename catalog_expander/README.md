# 渠道商品目录展开器

接收渠道明确提供的**有向父子关系**与**属性声明**，在有限无环图（DAG，允许
菱形/共享子节点/多根）上生成每个可售叶节点的有效属性、来源解释与精确包装
系数。不按名称匹配同款，不做价格、库存或订单管理。

## 输入格式（JSON）

```json
{
  "attributes": {"brand": "single", "color": "single", "tags": "set"},
  "nodes": [
    {"node": ["ch1", "R1"], "declarations": {
      "brand": {"mode": "single", "value": "Acme"},
      "color": {"mode": "single", "value": "red"},
      "tags":  {"base": "reset", "values": ["x", "y"], "add": [], "remove": []}
    }},
    {"node": ["ch1", "L"], "declarations": {
      "color": {"mode": "inherit"},
      "tags":  {"base": "inherit", "add": [], "remove": ["y"]}
    }}
  ],
  "edges": [
    {"parent": ["ch1", "R1"], "child": ["ch1", "L"], "pack_factor": 2}
  ]
}
```

- 节点身份是 `[channel, node_id]`；边允许前向引用稍后定义的节点。
- `pack_factor` 为正有理数：整数或 `"n/d"`；根系数为 1。
  含义：子项一销售单位 = 父项多少单位。
- single 声明：`{"mode": "inherit"}` / `{"mode": "block"}`
  / `{"mode": "single", "value": ...}`。
- set 声明：
  - `{"base": "inherit", "add": [...], "remove": [...]}`（add/remove 可省）
  - `{"base": "reset", "values": [...], "add": [...], "remove": [...]}`
  - `{"base": "block"}`
  - 同一记录 add/remove 不允许相交。

## 语义要点

### single

- 继承所有父节点的有效声明，`absent` 被忽略；全 absent 仍 absent。
- 相同值合并证据；值不同、block 与值并存、或父冲突存在 => `conflict`。
- 本节点 `single(value)` 或 `block` 显式覆盖任何传入状态（含冲突），
  被覆盖来源保留在解释链中。
- block 是显式“不适用”，不会被当作缺值重新继承。

### set

- 先对父有效集合取并，再按 base -> add -> remove 顺序应用本地操作。
- `remove` 只影响本次集合，不是后代黑名单；后代可重新 add 回该元素。
- `reset` 从给定 `values` 起算，不继承父值，可覆盖父 conflict/blocked。
- `block` 是独立记录形式；父 block 与实际集合并存 => conflict；
  全 block => blocked；add/remove 不能覆盖父 conflict。
- 父为 blocked 且本地有 add/remove => 输入语义冲突（不猜成空集）。
- 空集合是 `value`（空 tuple），与 absent/blocked 严格区分。

### 包装系数

- 沿每条根->叶路径逐边相乘；同一节点经不同路径得到的系数必须相同才交付，
  否则该节点（及经其向下的支系）包装为 `conflict`。
- 多条路径**不相加**（不是多份商品），也不只选一条；属性冲突与包装冲突
  互不抹除：包装冲突不影响已唯一确定的品牌。
- 父包装冲突只沿依赖它的边向下传播，不影响其他根下的节点。

所有输出状态统一为 `value / absent / blocked / conflict`。

## API

```python
from catalog import build_catalog, NodeRef

store = build_catalog(spec, db_path="catalog.db")  # 或 ":memory:"
store.list_leaves()
leaf = store.read_leaf(NodeRef("ch1", "L"))
leaf.attributes["brand"]          # AttrState(status, value, evidence_id)
leaf.pack                         # PackState(status, factor, evidence_id)
store.explain_attr(NodeRef("ch1", "L"), "color")   # 展开到原声明
store.explain_pack(NodeRef("ch1", "L"))            # 展开到各路径候选与边
store.stats()                     # 实际处理的节点/边/证据数与状态分布
```

证据是**共享证据图**：菱形中相同内容的证据节点内容寻址去重，叶节点只存
证据 id，不为每条叶复制原始路径。`explain_*` 递归展开（带环保护、共享节点
只展开一次），`primitives` 给出去重后的原声明，包装解释另给出涉及的边。

## 结构错误（整次失败，抛 `StructuralError`）

未知父/子节点、环（含自环）、重复节点/边、坏有理数（0、负数、小数、
零分母等）、未知属性、声明形状非法、set add/remove 相交。
**属性冲突不是错误**，是必须保留的正常输出。

## 实现约束

- 正式实现按 Kahn 拓扑序逐节点合并，时间/空间与节点+边数同阶，
  不枚举根到叶路径（深菱形/十万节点材料测试验证不会路径爆炸）。
- 结果落盘 SQLite（`nodes/edges/attributes/attr_states/pack_states/evidence/meta`）。
- `catalog/enumerator.py` 是独立的小图朴素路径枚举器，**仅测试用**，
  与正式实现交叉核对。

## 运行

```bash
cd catalog_expander
python -m unittest discover -s tests -v
python -m catalog.demo sample_input.json
```
