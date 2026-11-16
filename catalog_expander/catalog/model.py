"""领域模型与状态常量。"""
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional, Tuple

# 属性/包装的四种（属性）状态。空集合属于 value。
VALUE = "value"
ABSENT = "absent"
BLOCKED = "blocked"
CONFLICT = "conflict"

SINGLE = "single"
SET = "set"


@dataclass(frozen=True)
class NodeRef:
    """节点身份：channel + node_id。"""

    channel: str
    node_id: str

    def as_pair(self) -> Tuple[str, str]:
        return (self.channel, self.node_id)

    @classmethod
    def of(cls, pair: Tuple[str, str]) -> "NodeRef":
        return cls(channel=pair[0], node_id=pair[1])

    def to_json(self):
        return [self.channel, self.node_id]


@dataclass
class AttrState:
    """单个节点单个属性的有效状态。

    kind:   single / set
    status: value / absent / blocked / conflict
    value:  single 为标量；set 为排序后的 tuple；其余状态为 None
    evidence_id: 共享证据图中的根证据节点（absent 且无任何来源时为 None）
    """

    attr: str
    kind: str
    status: str
    value: Any = None
    evidence_id: Optional[str] = None

    def to_dict(self) -> dict:
        out = {"attr": self.attr, "kind": self.kind, "status": self.status}
        if self.status == VALUE:
            if self.kind == SET:
                out["value"] = list(self.value)
            else:
                out["value"] = self.value
        if self.evidence_id is not None:
            out["evidence_id"] = self.evidence_id
        return out


@dataclass
class PackState:
    """节点的有效包装系数（根为 1；多路径不一致时 conflict）。"""

    status: str  # value / conflict
    factor: Optional[Fraction]
    evidence_id: Optional[str]

    def to_dict(self) -> dict:
        out = {"status": self.status}
        if self.factor is not None:
            from .rational import frac_str

            out["factor"] = frac_str(self.factor)
        if self.evidence_id is not None:
            out["evidence_id"] = self.evidence_id
        return out


@dataclass
class LeafResult:
    """一个可售叶节点的完整展开结果。"""

    node: NodeRef
    attributes: dict  # attr -> AttrState
    pack: PackState

    def to_dict(self) -> dict:
        return {
            "node": self.node.to_json(),
            "attributes": {a: s.to_dict() for a, s in self.attributes.items()},
            "pack": self.pack.to_dict(),
        }
