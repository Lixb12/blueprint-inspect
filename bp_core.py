# -*- coding: utf-8 -*-
"""
bp_core.py —— 蓝图结构解析核心（被 inspect 入口与 HTML 流程图复用）。

只依赖标准库；输入为 uasset.exe --json 导出的 JSON，产出：
  - 按图表分组的节点清单（含中文类型 / 作用说明 / 坐标 / 引脚）
  - 引脚级连线表
"""

import json
import csv
import os
import subprocess
import tempfile


# ---------------------------------------------------------------------------
# 释义字典：可按项目需要继续扩充
# ---------------------------------------------------------------------------

NODE_CLASS_CN = {
    "K2Node_Event": "事件",
    "K2Node_CallFunction": "函数调用",
    "K2Node_CallFunctionOnMember": "成员函数调用",
    "K2Node_VariableGet": "读取变量",
    "K2Node_VariableSet": "写入变量",
    "K2Node_PromotableOperator": "运算符",
    "K2Node_IfThenElse": "分支",
    "K2Node_CreateWidget": "创建控件",
    "K2Node_FunctionEntry": "函数入口",
    "K2Node_FunctionResult": "函数返回",
    "K2Node_ComponentBoundEvent": "组件事件",
    "K2Node_MacroInstance": "宏实例",
    "K2Node_AssignmentStatement": "赋值",
    "K2Node_Switch": "分支开关",
    "K2Node_DynamicCast": "类型转换",
    "K2Node_CustomEvent": "自定义事件",
    "EdGraphNode_Comment": "注释",
}

MEMBER_CN = {
    "AddToViewport": "添加到视口",
    "GetValue": "获取滑块当前值",
    "SetText": "设置文本",
    "Conv_DoubleToText": "数值转文本",
    "Conv_TextToString": "文本转字符串",
    "MakeLiteralText": "构造字面量文本",
    "CreateDynamicMaterialInstance": "创建动态材质实例",
    "SetScalarParameterValue": "设置材质标量参数",
    "GetActorOfClass": "按类查找场景 Actor",
    "GetComponentByClass": "按类查找组件",
    "SetVariableFloat": "设置 Niagara 浮点变量",
    "MapRangeClamped": "区间映射(夹取)",
    "FClamp": "数值夹取到范围",
    "CalcErosionAmount": "计算侵蚀量",
    "CalcRunoff": "计算径流量",
    "ReceiveBeginPlay": "开始运行时事件",
    "ReceiveTick": "每帧 Tick 事件",
}

OPERATOR_CN = {
    "Multiply": "乘法 (A × B)",
    "Add": "加法 (A + B)",
    "Subtract": "减法 (A − B)",
    "Divide": "除法 (A ÷ B)",
    "Greater": "大于 (A > B)",
    "Less": "小于 (A < B)",
    "Equal": "相等 (A == B)",
    "BooleanAnd": "逻辑与",
    "BooleanOr": "逻辑或",
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def member_ref(props, key):
    ref = props.get(key)
    if isinstance(ref, dict):
        return {"name": ref.get("MemberName", ""), "parent": ref.get("MemberParent", "")}
    return {"name": "", "parent": ""}


def short_parent(parent):
    if not parent:
        return ""
    return parent.rsplit(".", 1)[-1]


def node_kind(node):
    cls = node.get("class", "")
    props = node.get("properties", {})
    if cls == "K2Node_CallFunction":
        return "function", member_ref(props, "FunctionReference")
    if cls == "K2Node_VariableGet":
        return "variable_get", member_ref(props, "VariableReference")
    if cls == "K2Node_VariableSet":
        return "variable_set", member_ref(props, "VariableReference")
    if cls == "K2Node_Event":
        return "event", member_ref(props, "EventReference")
    if cls == "K2Node_ComponentBoundEvent":
        return "bound_event", member_ref(props, "EventReference")
    if cls == "K2Node_PromotableOperator":
        return "operator", {"name": props.get("OperationName", ""), "parent": ""}
    if cls in ("K2Node_FunctionEntry", "K2Node_FunctionResult"):
        return "function_io", member_ref(props, "FunctionReference")
    if cls == "K2Node_CreateWidget":
        return "create_widget", {"name": "", "parent": ""}
    if cls == "K2Node_IfThenElse":
        return "branch", {"name": "", "parent": ""}
    return "other", {"name": "", "parent": ""}


def _pin_type_of(node):
    """取节点第一个数据引脚的类型（用于变量节点推断变量类型）。"""
    for pin in node.get("pins", []):
        if pin.get("direction") == "out" and pin.get("type") not in ("exec", None):
            return pin.get("type", "unknown")
    for pin in node.get("pins", []):
        if pin.get("direction") == "in" and pin.get("type") not in ("exec", None):
            return pin.get("type", "unknown")
    return "unknown"


def describe_node(node):
    """返回 dict: kind / cn_type / member / parent / title / desc / x / y。

    title 为节点自身标题（不含图表前缀）；图表归属由 graphs 分组与 CSV 的 Graph 列表达，
    避免在报告已分节的表格里重复冗长的图表路径。
    """
    cls = node.get("class", "")
    name = node.get("name", "")
    props = node.get("properties", {})
    kind, ref = node_kind(node)

    cn_type = NODE_CLASS_CN.get(cls, cls)
    member = ref.get("name", "")
    parent = short_parent(ref.get("parent", ""))
    var_type = _pin_type_of(node) if kind in ("variable_get", "variable_set") else ""

    title_parts = [cn_type]
    if parent:
        title_parts.append(parent)
    if member:
        title_parts.append(member)
    title_parts.append(f"({name})")
    title = " · ".join(title_parts)

    if kind == "function":
        action = MEMBER_CN.get(member, f"调用函数 {member}")
        desc = f"调用 {parent + '::' if parent else ''}{member}：{action}"
    elif kind == "variable_get":
        desc = f"读取变量「{member}」"
    elif kind == "variable_set":
        desc = f"写入变量「{member}」"
    elif kind == "event":
        desc = f"事件节点：{MEMBER_CN.get(member, member)}"
    elif kind == "bound_event":
        comp = props.get("ComponentPropertyName", "")
        delegate = props.get("DelegatePropertyName", "")
        desc = f"组件 {comp} 的 {delegate} 事件触发后执行"
    elif kind == "operator":
        desc = OPERATOR_CN.get(member, f"运算符 {member}")
    elif kind == "function_io":
        if cls == "K2Node_FunctionEntry":
            desc = f"函数「{member}」入口，接收输入参数"
        else:
            desc = f"函数「{member}」返回节点，输出结果"
    elif kind == "create_widget":
        desc = "创建 UMG 控件实例"
    elif kind == "branch":
        desc = "条件判断：成立走 True，否则走 False"
    elif cls == "EdGraphNode_Comment":
        comment_text = props.get("CommentText") or props.get("NodesUnderComment") or ""
        desc = f"注释框：{comment_text}" if comment_text else "注释框（无文字）"
    else:
        desc = f"节点 {name}（类型 {cls}）"

    comment_text = ""
    if cls == "EdGraphNode_Comment":
        comment_text = props.get("CommentText") or props.get("NodesUnderComment") or ""

    return {
        "kind": kind,
        "cn_type": cn_type,
        "member": member,
        "parent": parent,
        "var_type": var_type,
        "comment": comment_text,
        "title": title,
        "desc": desc,
        "name": name,
        "x": props.get("NodePosX", 0),
        "y": props.get("NodePosY", 0),
        "guid": props.get("NodeGuid", ""),
    }


def collect_graphs(exports):
    """返回 {graph: [node, ...]}。

    保留带引脚的图表节点；注释框（EdGraphNode_Comment）没有引脚，也一并保留，
    否则其文字批注会被直接丢弃。
    """
    graphs = {}
    for node in exports:
        cls = node.get("class", "")
        has_pins = bool(node.get("pins"))
        is_comment = cls == "EdGraphNode_Comment"
        if not (has_pins or is_comment):
            continue
        path = node.get("path", "")
        graph = path.rsplit(".", 1)[0] if "." in path else "(全局)"
        graphs.setdefault(graph, []).append(node)
    return graphs


def build_index(exports):
    node_by_path = {}
    pin_guid_map = {}
    for node in exports:
        path = node.get("path", "")
        node_by_path[path] = node
        for pin in node.get("pins", []):
            guid = pin.get("id")
            if guid:
                pin_guid_map[guid] = (path, pin.get("name", "?"))
    return node_by_path, pin_guid_map


def collect_links(exports, pin_guid_map, label_by_path):
    records = []
    for node in exports:
        path = node.get("path", "")
        src_label = label_by_path.get(path, path)
        for pin in node.get("pins", []):
            if pin.get("direction") != "out":
                continue
            pin_name = pin.get("name", "?")
            pin_type = pin.get("type", "unknown")
            guid = pin.get("id", "")
            is_exec = pin_type == "exec" or pin_name in ("then", "execute")
            for link in pin.get("links", []):
                target_node = link.get("node", "")
                target_pin_guid = link.get("pin", "")
                t_path, target_pin_name = target_node, "?"
                if target_pin_guid in pin_guid_map:
                    t_path, target_pin_name = pin_guid_map[target_pin_guid]
                t_label = label_by_path.get(t_path, short_parent(target_node))
                records.append({
                    "Graph": path.rsplit(".", 1)[0] if "." in path else "",
                    "SourceNode": src_label,
                    "SourcePath": path,
                    "SourcePin": pin_name,
                    "SourcePinType": pin_type,
                    "IsExec": is_exec,
                    "TargetNode": t_label,
                    "TargetPath": t_path,
                    "TargetPin": target_pin_name,
                    "SourcePinGuid": guid,
                    "TargetPinGuid": target_pin_guid,
                })
    return records


def parse_asset(asset_path, uasset_bin=""):
    """统一入口：接受 .json / .uasset / .umap，返回 (exports, imports, base_name)。"""
    if asset_path.lower().endswith(".json"):
        data = load_json(asset_path)
    else:
        if not uasset_bin or not os.path.isfile(uasset_bin):
            raise SystemExit("需要 uasset.exe：用 --uasset-bin 指定，或先手动导出 JSON")
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="bp_")
        os.close(fd)
        try:
            subprocess.run([uasset_bin, "--json", "-o", tmp, asset_path],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or "").strip()
            raise SystemExit(f"uasset.exe 解析失败: {os.path.basename(asset_path)}\n{detail}")
        except FileNotFoundError:
            raise SystemExit(f"找不到 uasset.exe: {uasset_bin}")
        data = load_json(tmp)
        os.remove(tmp)
    exports = data.get("exports", [])
    imports = data.get("imports", [])
    base = os.path.splitext(os.path.basename(asset_path))[0]
    return exports, imports, base


def is_blueprint_asset(exports):
    """依据导出项里是否含蓝图/图表节点，判断这是不是可分析的蓝图或关卡脚本。

    材质、贴图、静态模型、Niagara 系统等导出项里没有 K2/EdGraph 节点，判为 False。
    """
    bp_prefixes = ("K2Node_", "EdGraphNode_")
    for node in exports:
        cls = node.get("class", "")
        if cls.startswith(bp_prefixes):
            return True
    return False


def list_referenced_blueprints(imports):
    """提取本资产引用的蓝图类（BlueprintGeneratedClass），返回去重后的路径/类名列表。"""
    refs = {}
    for imp in imports:
        if imp.get("class") != "BlueprintGeneratedClass":
            continue
        path = imp.get("path", "")
        cls = path.rsplit(".", 1)[-1] if path else imp.get("class", "")
        # 去掉 Default__ 前缀的默认对象，只保留类本身
        if cls.startswith("Default__"):
            continue
        asset_path = path.rsplit(".", 1)[0] if "." in path else path
        refs[asset_path] = cls
    return [{"asset": p, "class": c} for p, c in refs.items()]


def content_dir_from_asset(asset_path):
    """逐级向上查找 Content 目录；找不到则返回资产所在目录。"""
    d = os.path.dirname(os.path.abspath(asset_path))
    while True:
        if os.path.basename(d).lower() == "content":
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(os.path.abspath(asset_path))


def _norm_rel(rel):
    """把相对路径规范化为小写、正斜杠、去掉扩展名，便于大小写/分隔符无关比对。"""
    rel = rel.replace(os.sep, "/").replace("\\", "/")
    if rel.lower().endswith(".uasset"):
        rel = rel[:-len(".uasset")]
    return rel.strip("/").lower()


def resolve_game_path(game_path, content_dir):
    """/Game/Folder/X -> Content/Folder/X.uasset；找不到返回 None。"""
    if not game_path.startswith("/Game/"):
        return None
    rel = game_path[len("/Game/"):]
    candidate = os.path.join(content_dir, rel + ".uasset")
    if os.path.isfile(candidate):
        return candidate
    # 兜底：不区分大小写、不区分分隔符与扩展名差异，按目录逐项匹配
    target_norm = _norm_rel(rel)
    for root, _dirs, files in os.walk(content_dir):
        for fn in files:
            if not fn.lower().endswith(".uasset"):
                continue
            full = os.path.join(root, fn)
            rel_full = os.path.relpath(full, content_dir)
            if _norm_rel(rel_full) == target_norm:
                return full
    return None


def analyze(exports):
    """组装节点说明与连线，返回 dict 供各输出器使用。"""
    graphs = collect_graphs(exports)
    node_by_path, pin_guid_map = build_index(exports)
    label_by_path = {}
    info_by_path = {}
    for path, node in node_by_path.items():
        info = describe_node(node)
        label_by_path[path] = info["title"]
        info_by_path[path] = info
    records = collect_links(exports, pin_guid_map, label_by_path)
    dangling = collect_dangling_inputs(exports, pin_guid_map)
    return {"graphs": graphs, "node_by_path": node_by_path,
            "info_by_path": info_by_path, "links": records, "dangling": dangling}


def collect_dangling_inputs(exports, pin_guid_map):
    """收集未连接的可见输入引脚（悬空引脚），按图表分组返回。"""
    # 先收集所有被连线引用到的输入引脚 GUID
    connected_targets = set()
    for node in exports:
        for pin in node.get("pins", []):
            if pin.get("direction") != "out":
                continue
            for link in pin.get("links", []):
                if link.get("pin"):
                    connected_targets.add(link["pin"])

    dangling = {}
    for node in exports:
        path = node.get("path", "")
        graph = path.rsplit(".", 1)[0] if "." in path else "(全局)"
        for pin in node.get("pins", []):
            if pin.get("direction") != "in" or pin.get("hidden"):
                continue
            if pin.get("id") in connected_targets:
                continue
            # self / execute 这类框架引脚不算业务悬空引脚
            if pin.get("name") in ("self", "execute", "then", "__WorldContext"):
                continue
            dangling.setdefault(graph, []).append({
                "node": path,
                "pin": pin.get("name", "?"),
                "type": pin.get("type", "unknown"),
                "default": pin.get("default", ""),
            })
    return dangling


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------

def write_node_csv(graphs, info_by_path, path):
    fieldnames = ["Graph", "NodeType", "Member", "VarType", "NodeLabel",
                  "Description", "NodeName", "NodeGuid"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for graph, nodes in graphs.items():
            for node in nodes:
                info = info_by_path[node["path"]]
                w.writerow({
                    "Graph": graph, "NodeType": info["cn_type"], "Member": info["member"],
                    "VarType": info.get("var_type", ""), "NodeLabel": info["title"],
                    "Description": info["desc"],
                    "NodeName": info["name"], "NodeGuid": info["guid"],
                })


def write_links_csv(records, path):
    fieldnames = ["Graph", "SourceNode", "SourcePath", "SourcePin", "SourcePinType", "IsExec",
                  "TargetNode", "TargetPath", "TargetPin", "SourcePinGuid", "TargetPinGuid"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(records)
