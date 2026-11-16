"""测试辅助：构造输入片段。"""


def node(channel, node_id, declarations=None):
    out = {"node": [channel, node_id]}
    if declarations:
        out["declarations"] = declarations
    return out


def edge(parent, child, factor=1):
    return {
        "parent": list(parent),
        "child": list(child),
        "pack_factor": factor,
    }


def spec(attributes, nodes, edges):
    return {"attributes": attributes, "nodes": nodes, "edges": edges}


def single(value):
    return {"mode": "single", "value": value}


def inherit():
    return {"mode": "inherit"}


def block():
    return {"mode": "block"}


def set_inherit(add=(), remove=()):
    return {"base": "inherit", "add": list(add), "remove": list(remove)}


def set_reset(values, add=(), remove=()):
    return {
        "base": "reset", "values": list(values),
        "add": list(add), "remove": list(remove),
    }


def set_block():
    return {"base": "block"}
