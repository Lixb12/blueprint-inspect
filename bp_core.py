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
import argparse


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

# 节点类型 -> HTML 卡片配色（流程图用）
KIND_COLOR = {
    "event": "#c0392b",
    "function": "#2980b9",
    "variable_get": "#27ae60",
    "variable_set": "#16a085",
    "operator": "#8e44ad",
    "branch": "#d35400",
    "create_widget": "#2c3e50",
    "function_io": "#7f8c8d",
    "bound_event": "#c0392b",
    "create_widget2": "#2c3e50",
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


def describe_node(node):
    """返回 dict: kind / cn_type / member / parent / title / desc / x / y。"""
    cls = node.get("class", "")
    name = node.get("name", "")
    props = node.get("properties", {})
    kind, ref = node_kind(node)

    cn_type = NODE_CLASS_CN.get(cls, cls)
    member = ref.get("name", "")
    parent = short_parent(ref.get("parent", ""))

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
    else:
        desc = f"节点 {name}（类型 {cls}）"

    return {
        "kind": kind,
        "cn_type": cn_type,
        "member": member,
        "parent": parent,
        "title": title,
        "desc": desc,
        "name": name,
        "x": props.get("NodePosX", 0),
        "y": props.get("NodePosY", 0),
        "guid": props.get("NodeGuid", ""),
    }


def collect_graphs(exports):
    """返回 {graph: [node, ...]}，仅保留带引脚的图表节点。"""
    graphs = {}
    for node in exports:
        if not node.get("pins"):
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
        subprocess.run([uasset_bin, "--json", "-o", tmp, asset_path],
                       check=True, capture_output=True, text=True)
        data = load_json(tmp)
        os.remove(tmp)
    exports = data.get("exports", [])
    imports = data.get("imports", [])
    base = os.path.splitext(os.path.basename(asset_path))[0]
    return exports, imports, base


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
    """从一个资产路径反推 Content 目录（.uasset/.umap 所在的上一级 Content）。"""
    d = os.path.dirname(os.path.abspath(asset_path))
    # 常见布局: Content/XXX.uasset 或 Content/子目录/XXX.uasset，Content 即目录本身
    if os.path.basename(d).lower() == "content":
        return d
    # 向上找一层名为 Content 的目录
    parent = os.path.dirname(d)
    if os.path.basename(parent).lower() == "content":
        return parent
    return d


def resolve_game_path(game_path, content_dir):
    """/Game/Folder/X -> Content/Folder/X.uasset；找不到返回 None。"""
    if not game_path.startswith("/Game/"):
        return None
    rel = game_path[len("/Game/"):]
    candidate = os.path.join(content_dir, rel + ".uasset")
    if os.path.isfile(candidate):
        return candidate
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
    return {"graphs": graphs, "node_by_path": node_by_path,
            "info_by_path": info_by_path, "links": records}


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------

def write_node_csv(graphs, info_by_path, path):
    fieldnames = ["Graph", "NodeType", "Member", "NodeLabel", "Description", "NodeName", "NodeGuid"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for graph, nodes in graphs.items():
            for node in nodes:
                info = info_by_path[node["path"]]
                w.writerow({
                    "Graph": graph, "NodeType": info["cn_type"], "Member": info["member"],
                    "NodeLabel": info["title"], "Description": info["desc"],
                    "NodeName": info["name"], "NodeGuid": info["guid"],
                })


def write_links_csv(records, path):
    fieldnames = ["Graph", "SourceNode", "SourcePath", "SourcePin", "SourcePinType", "IsExec",
                  "TargetNode", "TargetPath", "TargetPin", "SourcePinGuid", "TargetPinGuid"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(records)
