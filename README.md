# 蓝图结构查看工具（轻量）

分析 UE 的 `.uasset` / `.umap` 蓝图资产，输出**节点清单 + 每个节点的作用说明 + 引脚级连线描述**（纯文本/表格，不含可视化图形界面）。

## 一、最快上手（新手）

**方式 A：拖拽运行（推荐）**
把任意 `.uasset` / `.umap` 文件直接拖到 **`查看蓝图.bat`** 图标上，等待完成。

**方式 B：双击运行**
双击 `查看蓝图.bat`，按提示把文件路径粘贴进去回车。

**方式 C：命令行**
```powershell
python bp_inspect.py "D:/UE_Project/TestDemo1/Content/WBP_HUD.uasset"
```

结果默认生成在 **`D:\Blueprint_Output`** 文件夹（可用 `-o` 改到其他目录）：

| 文件 | 内容 |
|---|---|
| `<名>_nodes.csv` | 节点清单 + 中文作用说明 + 变量类型（Excel 可打开） |
| `<名>_links.csv` | 引脚级连线表（源/目标节点·引脚·类型·GUID） |
| `<名>_report.md` | 可读 Markdown 报告（节点清单 + 连线描述 + 悬空输入引脚 + 注释框 + 引用蓝图） |
| `index.md` | 本次运行所有蓝图的汇总索引（图表/节点/连线数量 + 引用关系） |

## 二、命令行参数（一般不用填）

```powershell
# 单个文件
python bp_inspect.py "D:/UE_Project/TestDemo1/Content/WBP_HUD.uasset"

# 多个文件（一次拖入多个）
python bp_inspect.py MainLevel.umap WBP_HUD.uasset BFL_ErosionCalc.uasset

# 整个 Content 目录（自动递归扫描其中的蓝图/关卡）
python bp_inspect.py "D:/UE_Project/TestDemo1/Content"
```

| 参数 | 默认 | 说明 |
|---|---|---|
| 资产路径 | 必填 | `.uasset` / `.umap` / `.json` 文件，或一个目录；可传多个，可直接拖入窗口 |
| `-o` | `D:\Blueprint_Output` | 输出目录 |
| `-b` | 自动在下载目录查找 | `uasset.exe` 解析器路径 |
| `--no-csv` | 关闭 | 不生成 CSV，只出 Markdown 报告 |
| `--no-recursive` | 关闭 | 不跟随关卡引用的蓝图类，只分析当前文件（默认会自动递归分析关联蓝图） |

**目录扫描**：传入文件夹时，会自动遍历其中所有 `.uasset` / `.umap`；材质、贴图、静态模型等不含图表节点的资产自动跳过，不产生空报告。

**递归行为**：拖入 `.umap` 时，工具默认按引用路径自动找到 `Content/` 下关联的 `.uasset` 一并分析，输出里每个蓝图各一组 CSV/报告；自动去重、防循环；找不到对应文件会提示跳过。只想看当前文件时加 `--no-recursive`。

> 若传入的是已有 JSON（由 `uasset.exe --json` 导出），则不需要 uasset.exe。

## 三、文件结构

```
bp_inspect.py      命令行入口（新手从这里进）
bp_core.py         解析核心：节点识别、说明生成、连线提取、悬空引脚统计
查看蓝图.bat        双击/拖拽启动器
D:\Blueprint_Output  生成结果（首次运行后自动创建）
```

## 四、节点说明是怎么来的

按 UE 节点类自动识别，从资产原始引用中提取成员名：

| 节点类 | 识别为 | 说明来源 |
|---|---|---|
| `K2Node_Event` | 事件 | `EventReference.MemberName` |
| `K2Node_CallFunction` | 函数调用 | `FunctionReference.MemberName` + 父类 |
| `K2Node_VariableGet/Set` | 读/写变量 | `VariableReference.MemberName` |
| `K2Node_PromotableOperator` | 运算符 | `OperationName` |
| `K2Node_IfThenElse` | 分支 | 固定说明 |
| `K2Node_FunctionEntry/Result` | 函数入口/返回 | `FunctionReference.MemberName` |
| `K2Node_ComponentBoundEvent` | 组件事件 | 组件名 + 委托名 |

**扩充中文释义**：编辑 `bp_core.py` 顶部的 `MEMBER_CN`（函数动作）、`OPERATOR_CN`（运算符）、`NODE_CLASS_CN`（类型名）字典即可；未命中的成员回退显示原始英文名，不会报错。

## 五、已验证资产

关卡脚本蓝图、Actor 蓝图、UMG 控件蓝图、函数库四类均跑通；连线为资产原始引脚连接，不做行为推断。少量原资产中带断连/异常标记的节点会如实保留，不补线、不猜测。

**关卡引用清单**：解析 `.umap` 时，报告会额外列出本关卡引用到的蓝图类（`BlueprintGeneratedClass`）及其资产路径；这些类的节点连线需要再拖对应的 `.uasset` 文件单独分析。

## 六、局限与可扩展项

- 控件层级树（Widget 树）暂未输出，可在 `bp_core.py` 中按需扩展。
- 报告已包含：变量类型、未连接输入引脚清单、注释框文字、汇总索引 `index.md`。
- 二进制兼容（UE 4.21–5.8）由外部 `uasset.exe` 解析器保证；本工具只消费其 JSON。
