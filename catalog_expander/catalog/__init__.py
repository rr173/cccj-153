"""渠道商品目录展开器。

公开入口：
    build_catalog(spec, db_path=":memory:") -> CatalogStore
    CatalogStore                            读取/解释入口
    StructuralError                         结构错误（整次失败）
"""
from .errors import StructuralError
from .model import (
    ABSENT,
    BLOCKED,
    CONFLICT,
    VALUE,
    AttrState,
    LeafResult,
    NodeRef,
    PackState,
)
from .store import CatalogStore
from .builder import build_catalog

__all__ = [
    "build_catalog",
    "CatalogStore",
    "StructuralError",
    "NodeRef",
    "AttrState",
    "PackState",
    "LeafResult",
    "VALUE",
    "ABSENT",
    "BLOCKED",
    "CONFLICT",
]
