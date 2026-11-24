# -*- coding: utf-8 -*-
"""
蓝图结构查看工具 —— 新手友好入口（节点清单 + 连线描述）

最简用法（把文件直接拖到本脚本上，或命令行传文件路径）:
    python bp_inspect.py MainLevel.umap
    python bp_inspect.py "D:/UE_Project/TestDemo1/Content/WBP_HUD.uasset"
    python bp_inspect.py MainLevel.json

可选参数（一般不用填）:
    -o 输出目录            默认: D:/Blueprint_Output
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
import hashlib

# 输出重定向到文件/管道时，Windows 默认 GBK 编码遇到 ✔/✖/中文 会抛 UnicodeEncodeError。
# 启动即把标准流重配为 UTF-8；不支持重配的环境退回替换策略，保证打印不崩溃。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import bp_core

# 记录输出目录内已占用的文件前缀，避免不同目录下的同名蓝图互相覆盖
_used_prefixes = {}


def _unique_prefix(base, asset_path, output_dir):
    """返回不与已产出文件冲突的前缀；同名时追加路径短哈希。"""
    abs_path = os.path.abspath(asset_path)
    prefix = base
    if prefix in _used_prefixes and _used_prefixes[prefix] != abs_path:
        digest = hashlib.md5(abs_path.encode("utf-8")).hexdigest()[:4]
        prefix = f"{base}_{digest}"
    _used_prefixes[prefix] = abs_path
    return prefix

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
    dangling = analysis.get("dangling", {})
    lines = [f"# 蓝图结构报告：{asset_name}", ""]
    lines.append(f"- 图表数：{len(graphs)}")
    total = sum(len(v) for v in graphs.values())
    lines.append(f"- 节点总数：{total}")
    lines.append(f"- 连线总数（输出→输入）：{len(links)}")
    dangling_total = sum(len(v) for v in dangling.values())
    lines.append(f"- 未连接输入引脚：{dangling_total} 个")
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
        g_dangling = dangling.get(graph, [])
        if g_dangling:
            lines.append("### 未连接的输入引脚")
            lines.append("")
            lines.append("| 节点 | 引脚 | 类型 | 默认值 |")
            lines.append("|---|---|---|---|")
            for d in g_dangling:
                node_label = info_by_path.get(d["node"], {}).get("title", d["node"])
                default = d["default"] if d["default"] != "" else "—"
                lines.append(f"| {node_label} | {d['pin']} | {d['type']} | {default} |")
            lines.append("")
        g_comments = [info_by_path[n["path"]] for n in nodes
                      if info_by_path[n["path"]].get("comment")]
        if g_comments:
            lines.append("### 注释框")
            lines.append("")
            for c in g_comments:
                lines.append(f"- {c['comment']}")
            lines.append("")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))


def analyze_and_write(asset_path, output_dir, uasset_bin, make_csv=True, depth=0,
                      quiet_skip=False):
    """解析单个资产并写出 CSV/报告，返回结果字典（含 analysis / referenced / paths）。"""
    exports, imports, base = bp_core.parse_asset(asset_path, uasset_bin)
    analysis = bp_core.analyze(exports)
    referenced = bp_core.list_referenced_blueprints(imports)

    total = sum(len(v) for v in analysis["graphs"].values())
    indent = "  " * depth

    # 非蓝图资产（材质/贴图/模型等）或空图表：跳过写文件，避免刷屏与空产物
    if total == 0 or not bp_core.is_blueprint_asset(exports):
        if not quiet_skip:
            print(f"{indent}· {base}: 无蓝图节点，已跳过")
        return {"base": base, "asset_path": asset_path, "analysis": analysis,
                "referenced": referenced, "paths": {}, "skipped": True}

    os.makedirs(output_dir, exist_ok=True)
    prefix = _unique_prefix(base, asset_path, output_dir)
    paths = {}

    if make_csv:
        nodes_csv = os.path.join(output_dir, f"{prefix}_nodes.csv")
        links_csv = os.path.join(output_dir, f"{prefix}_links.csv")
        bp_core.write_node_csv(analysis["graphs"], analysis["info_by_path"], nodes_csv)
        bp_core.write_links_csv(analysis["links"], links_csv)
        paths["nodes"] = nodes_csv
        paths["links"] = links_csv

    report_md = os.path.join(output_dir, f"{prefix}_report.md")
    write_report_md(analysis, base, report_md, referenced)
    paths["report"] = report_md

    print(f"{indent}✔ {base}: 图表 {len(analysis['graphs'])} ｜ 节点 {total} ｜ "
          f"连线 {len(analysis['links'])} ｜ 引用蓝图 {len(referenced)} 个")
    for k, p in paths.items():
        print(f"{indent}    {k}: {p}")

    return {"base": base, "prefix": prefix, "asset_path": asset_path,
            "analysis": analysis, "referenced": referenced,
            "paths": paths, "skipped": False}


def inspect_recursive(asset_path, output_dir, uasset_bin, make_csv=True,
                      follow_refs=True, quiet_skip=False):
    """分析主资产；可选递归解析其引用的蓝图类，避免重复与循环。"""
    main = analyze_and_write(asset_path, output_dir, uasset_bin, make_csv,
                             quiet_skip=quiet_skip)
    if not follow_refs:
        return [main]

    content_dir = bp_core.content_dir_from_asset(asset_path)
    seen = {os.path.abspath(asset_path)}
    results = [main]
    queue = list(main["referenced"])
    queued = {r["asset"] for r in queue}

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
            sub = analyze_and_write(resolved, output_dir, uasset_bin, make_csv,
                                    depth=1, quiet_skip=quiet_skip)
            results.append(sub)
            # 被引用蓝图若又引用其他蓝图，继续加入队列（限一层引用扫描，够用且防失控）
            for extra in sub["referenced"]:
                if extra["asset"] not in queued:
                    queued.add(extra["asset"])
                    queue.append(extra)
        except SystemExit as e:
            print(f"  ⚠ 解析失败 {ref['asset']}: {e}")
    return results


def write_index(results, output_dir):
    """全部分析完成后，在输出目录生成汇总 index.md（按完整路径去重）。"""
    results = [r for r in results if not r.get("skipped")]
    if not results:
        return
    seen_path, unique = set(), []
    for r in results:
        key = os.path.abspath(r["asset_path"])
        if key in seen_path:
            continue
        seen_path.add(key)
        unique.append(r)
    results = unique
    os.makedirs(output_dir, exist_ok=True)
    lines = ["# 蓝图分析汇总索引", ""]
    lines.append(f"共 {len(results)} 个资产，每个资产一份 report.md / nodes.csv / links.csv。")
    lines.append("")
    lines.append("| 资产 | 来源路径 | 图表 | 节点 | 连线 | 引用蓝图 | 报告 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        a = r["analysis"]
        graph_n = len(a["graphs"])
        node_n = sum(len(v) for v in a["graphs"].values())
        link_n = len(a["links"])
        ref_n = len(r["referenced"])
        report_name = os.path.basename(r["paths"].get("report", ""))
        report_link = f"[{report_name}]({report_name})" if report_name else "—"
        src = r["asset_path"]
        lines.append(f"| {r['base']} | `{src}` | {graph_n} | {node_n} | {link_n} | {ref_n} | {report_link} |")
    lines.append("")
    # 引用关系清单（按 源资产-目标 去重）
    ref_rows, ref_seen = [], set()
    for r in results:
        for ref in r["referenced"]:
            key = (os.path.abspath(r["asset_path"]), ref["asset"])
            if key in ref_seen:
                continue
            ref_seen.add(key)
            ref_rows.append((r["base"], ref["asset"], ref["class"]))
    if ref_rows:
        lines.append("## 引用关系")
        lines.append("")
        lines.append("| 资产 | 引用的资产路径 | 蓝图类 |")
        lines.append("|---|---|---|")
        for src, asset, cls in ref_rows:
            lines.append(f"| {src} | {asset} | {cls} |")
        lines.append("")
    index_path = os.path.join(output_dir, "index.md")
    with open(index_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    print(f"✔ 汇总索引: {index_path}")


def resolve_inputs(paths):
    """把传入的文件/目录展开为待分析资产路径列表（去重，保持顺序）。"""
    exts = (".uasset", ".umap", ".json")
    resolved, seen = [], set()
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for fn in sorted(files):
                    if fn.lower().endswith(exts):
                        full = os.path.join(root, fn)
                        if full not in seen:
                            seen.add(full)
                            resolved.append(full)
        elif os.path.isfile(p):
            if p.lower().endswith(exts) and p not in seen:
                seen.add(p)
                resolved.append(p)
    return resolved


def main():
    ap = argparse.ArgumentParser(
        description="UE 蓝图/关卡节点与连线查看工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python bp_inspect.py MainLevel.umap\n"
               "  python bp_inspect.py WBP_HUD.uasset BP_GameMode.uasset\n"
               "  python bp_inspect.py D:/UE_Project/TestDemo1/Content")
    ap.add_argument("assets", nargs="+", help=".uasset / .umap / .json 文件或目录（可多个）")
    ap.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出目录")
    ap.add_argument("-b", "--uasset-bin", default="", help="uasset.exe 路径（默认自动查找）")
    ap.add_argument("--no-csv", action="store_true", help="不生成 CSV，只出 Markdown 报告")
    ap.add_argument("--no-recursive", action="store_true",
                    help="不跟随关卡引用的蓝图类，只分析当前文件")
    args = ap.parse_args()

    targets = resolve_inputs(args.assets)
    if not targets:
        print("✖ 未找到可分析的 .uasset / .umap / .json 文件")
        sys.exit(1)

    dir_inputs = {os.path.abspath(a) for a in args.assets if os.path.isdir(a)}

    uasset_bin = args.uasset_bin or find_uasset_bin()
    need_bin = any(not t.lower().endswith(".json") for t in targets)
    if need_bin and not uasset_bin:
        print("✖ 未找到 uasset.exe，请用 -b 指定它的路径。")
        sys.exit(1)

    all_results = []
    for target in targets:
        # 目录批量扫描时静默跳过材质/贴图/模型等非蓝图资产；直接拖入的单文件仍逐条提示
        quiet = any(os.path.abspath(target).startswith(d) for d in dir_inputs)
        results = inspect_recursive(
            target, args.output, uasset_bin,
            make_csv=not args.no_csv, follow_refs=not args.no_recursive,
            quiet_skip=quiet,
        )
        all_results.extend(results)

    write_index(all_results, args.output)
    kept = [r for r in all_results if not r.get("skipped")]
    skipped = [r for r in all_results if r.get("skipped")]
    if kept:
        print(f"\n共分析 {len(kept)} 个蓝图资产，结果在: {args.output}")
    else:
        print("\n未发现可分析的蓝图资产，未生成结果文件。")
    if skipped:
        print(f"另有 {len(skipped)} 个非蓝图资产（材质/贴图/模型等）已自动跳过")


if __name__ == "__main__":
    main()
