# -*- coding: utf-8 -*-
"""
蓝图结构查看工具 —— 新手友好入口（节点清单 + 连线描述）

最简用法（把文件直接拖到本脚本上，或命令行传文件路径）:
    python bp_inspect.py MainLevel.umap
    python bp_inspect.py "D:/UE_Project/TestDemo1/Content/WBP_HUD.uasset"
    python bp_inspect.py MainLevel.json

可选参数（一般不用填）:
    -o 输出目录            默认: 脚本目录/output
    -b uasset.exe 路径     默认: 自动在常见下载目录查找

输出（每个资产一组, 文件名前缀=资产名）:
    <名>_nodes.csv    节点清单 + 作用说明
    <名>_links.csv    引脚级连线表
    <名>_report.md    可读 Markdown 报告（节点 + 连线描述）
"""

import os
import sys
import glob
import argparse

import bp_core

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = r"D:\Blueprint_Output"

# 常见 uasset.exe 存放位置（可继续补充）
UASSET_SEARCH = [
    os.path.join(os.path.expanduser("~"), "Downloads"),
    HERE,
    r"C:\Users\荣耀\Downloads",
]


def find_uasset_bin():
    """在常见目录递归找 uasset.exe，找不到返回空串。"""
    for base in UASSET_SEARCH:
        if not os.path.isdir(base):
            continue
        hits = glob.glob(os.path.join(base, "**", "uasset.exe"), recursive=True)
        if hits:
            return hits[0]
    return ""


def write_report_md(analysis, asset_name, path, referenced=None):
    graphs = analysis["graphs"]
    info_by_path = analysis["info_by_path"]
    links = analysis["links"]
    lines = [f"# 蓝图结构报告：{asset_name}", ""]
    lines.append(f"- 图表数：{len(graphs)}")
    total = sum(len(v) for v in graphs.values())
    lines.append(f"- 节点总数：{total}")
    lines.append(f"- 连线总数（输出→输入）：{len(links)}")
    if referenced:
        lines.append(f"- 引用的蓝图类：{len(referenced)} 个")
    lines.append("")

    if referenced:
        lines.append("## 引用的蓝图类")
        lines.append("")
        lines.append("| 资产路径 | 蓝图类 |")
        lines.append("|---|---|")
        for ref in referenced:
            lines.append(f"| {ref['asset']} | {ref['class']} |")
        lines.append("")

    for graph, nodes in graphs.items():
        lines.append(f"## 图表：{graph}")
        lines.append("")
        lines.append("### 节点清单")
        lines.append("")
        lines.append("| # | 类型 | 成员 | 作用说明 | 节点编号 |")
        lines.append("|---|---|---|---|---|")
        for i, node in enumerate(nodes, 1):
            info = info_by_path[node["path"]]
            lines.append(f"| {i} | {info['cn_type']} | {info['member']} | "
                         f"{info['desc']} | {info['name']} |")
        lines.append("")
        g_links = [r for r in links if r["Graph"] == graph]
        if g_links:
            lines.append("### 连线")
            lines.append("")
            lines.append("| 源节点 · 引脚 | 类型 | 目标节点 · 引脚 |")
            lines.append("|---|---|---|")
            for r in g_links:
                lines.append(f"| {r['SourceNode']} · {r['SourcePin']} | "
                             f"{r['SourcePinType']} | {r['TargetNode']} · {r['TargetPin']} |")
            lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def analyze_and_write(asset_path, output_dir, uasset_bin, make_csv=True, depth=0):
    """解析单个资产并写出 CSV/报告，返回结果字典（含 analysis / referenced / paths）。"""
    exports, imports, base = bp_core.parse_asset(asset_path, uasset_bin)
    analysis = bp_core.analyze(exports)
    referenced = bp_core.list_referenced_blueprints(imports)

    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    if make_csv:
        nodes_csv = os.path.join(output_dir, f"{base}_nodes.csv")
        links_csv = os.path.join(output_dir, f"{base}_links.csv")
        bp_core.write_node_csv(analysis["graphs"], analysis["info_by_path"], nodes_csv)
        bp_core.write_links_csv(analysis["links"], links_csv)
        paths["nodes"] = nodes_csv
        paths["links"] = links_csv

    report_md = os.path.join(output_dir, f"{base}_report.md")
    write_report_md(analysis, base, report_md, referenced)
    paths["report"] = report_md

    total = sum(len(v) for v in analysis["graphs"].values())
    indent = "  " * depth
    print(f"{indent}✔ {base}: 图表 {len(analysis['graphs'])} ｜ 节点 {total} ｜ "
          f"连线 {len(analysis['links'])} ｜ 引用蓝图 {len(referenced)} 个")
    for k, p in paths.items():
        print(f"{indent}    {k}: {p}")

    return {"base": base, "asset_path": asset_path, "analysis": analysis,
            "referenced": referenced, "paths": paths}


def inspect_recursive(asset_path, output_dir, uasset_bin, make_csv=True, follow_refs=True):
    """分析主资产；可选递归解析其引用的蓝图类，避免重复与循环。"""
    main = analyze_and_write(asset_path, output_dir, uasset_bin, make_csv)
    if not follow_refs:
        return [main]

    content_dir = bp_core.content_dir_from_asset(asset_path)
    seen = {os.path.abspath(asset_path)}
    results = [main]
    queue = list(main["referenced"])

    while queue:
        ref = queue.pop(0)
        resolved = bp_core.resolve_game_path(ref["asset"], content_dir)
        if not resolved:
            print(f"  ⚠ 未在 Content 下找到: {ref['asset']}（{ref['class']}）")
            continue
        resolved_abs = os.path.abspath(resolved)
        if resolved_abs in seen:
            continue
        seen.add(resolved_abs)
        try:
            sub = analyze_and_write(resolved, output_dir, uasset_bin, make_csv, depth=1)
            results.append(sub)
            # 被引用蓝图若又引用其他蓝图，继续加入队列（限一层引用扫描，够用且防失控）
            for extra in sub["referenced"]:
                if extra["asset"] not in {r["asset"] for r in queue}:
                    queue.append(extra)
        except SystemExit as e:
            print(f"  ⚠ 解析失败 {ref['asset']}: {e}")
    return results


def main():
    ap = argparse.ArgumentParser(
        description="UE 蓝图/关卡节点与连线查看工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python bp_inspect.py MainLevel.umap\n"
               "  python bp_inspect.py WBP_HUD.uasset -o D:/out")
    ap.add_argument("asset", help=".uasset / .umap / .json 文件路径（可直接拖入）")
    ap.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出目录")
    ap.add_argument("-b", "--uasset-bin", default="", help="uasset.exe 路径（默认自动查找）")
    ap.add_argument("--no-csv", action="store_true", help="不生成 CSV，只出 Markdown 报告")
    ap.add_argument("--no-recursive", action="store_true",
                    help="不跟随关卡引用的蓝图类，只分析当前文件")
    args = ap.parse_args()

    if not os.path.isfile(args.asset):
        print(f"✖ 找不到文件: {args.asset}")
        sys.exit(1)

    uasset_bin = args.uasset_bin or find_uasset_bin()
    if not args.asset.lower().endswith(".json") and not uasset_bin:
        print("✖ 未找到 uasset.exe，请用 -b 指定它的路径。")
        sys.exit(1)

    results = inspect_recursive(
        args.asset, args.output, uasset_bin,
        make_csv=not args.no_csv, follow_refs=not args.no_recursive,
    )
    print(f"\n共分析 {len(results)} 个资产，结果在: {args.output}")


if __name__ == "__main__":
    main()
