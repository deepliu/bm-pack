# bm-cartonizer 后续优化续接 Prompt

下面这段可以直接作为新对话 prompt 使用，用于继续优化 `bm-pack / bm-cartonizer` 分箱算法。

```text
我在继续优化 Himool ERP 使用的 `bm-cartonizer` 分箱算法。

项目路径：
- bm-pack 主工程：`D:\python_project\pythonProject\bm-pack`
- benchmark 工程：`D:\python_project\pythonProject\bm-cartonizer-benchmark`
- ERP 工程：`D:\fu\Himool\erp`

当前目标：
继续优化 `bm-cartonizer`，让算法分箱方案更接近或优于 ERP 已发货手工分箱方案。当前优先级是：
1. SKU 总数量必须一致。
2. 不允许超重。
3. strict 模式下不允许低于箱型最小重量。
4. 箱数不多于手工方案。
5. 每箱 SKU 种类越少越好。
6. 当前硬上限：单箱 SKU 种类不超过 6。
7. 优先把单箱 SKU 种类控制到 3 或更低。

当前样本口径：
- 从 ERP 已发货手工分箱中导出样本。
- 只保留手工方案箱数 >= 2 的样本，因为单箱方案对分箱算法优化参考意义有限。
- 排除任意手工箱重量 < 12kg 的方案。
- 排除任意手工箱 SKU 种类 > 6 的方案。
- 当前导出结果只有 11 个有效样本：
  `[99, 94, 93, 89, 81, 75, 74, 54, 51, 45, 31]`
- 样本文件：
  `D:\python_project\pythonProject\bm-pack\examples\erp_shipped_manual_cases.json`
  `D:\python_project\pythonProject\bm-cartonizer-benchmark\data\erp_shipped_manual_cases.json`

当前 benchmark 口径：
- 只对比：
  - `0.1.2`
  - `0.3.0-current`
  - ERP 手工方案
- 去掉 `0.2.0`。
- 不使用 `manual_like`，两个版本都用 strict。
- 主 benchmark 不把 3D 几何校验作为硬约束，即 `geometry_check=False`。
- ERP 适配层暂时不要改，等当前 `0.3.0-current` 优化稳定后再考虑。

当前 `0.3.0-current` 已完成的关键优化：
1. `MAX_SKU_TYPES_CAP = 6`
   - 候选搜索不再使用无限 SKU 放宽。
   - `max_sku_types=3` 是起始偏好，内部最多放宽到 6。
2. 评分中加重 SKU 种类惩罚。
   - SKU 种类越少越优先。
   - 超过硬上限会强惩罚。
3. `optimize_quantities()` 移动 SKU 时也遵守 SKU 上限。
4. 新增 `Stage 1.5`
   - 小规模 whole-SKU 二分候选。
   - 用于解决类似 #97 的“多 SKU 可拆成 2 箱”问题。
5. 新增 `Stage 1.6`
   - 固定箱数、低 SKU 混装搜索。
   - 小 SKU 数订单才启用。
   - 最多拆分 1 个 SKU。
   - 目标是在不增加箱数、不破坏重量约束的前提下，把最大单箱 SKU 种类降到 3。
   - #89 已从“4 箱，最大单箱 4 SKU”优化为“4 箱，最大单箱 3 SKU”。

当前 benchmark 结果：
- 报告：
  `D:\python_project\pythonProject\bm-cartonizer-benchmark\reports\cartonizer_version_summary.md`
- 当前 11 个有效样本：

| 版本 | OK | <= 手工箱数 | > 手工箱数 | 最大单箱 SKU | 平均每箱 SKU |
|---|---:|---:|---:|---:|---:|
| 0.1.2 | 11/11 | 9 | 2 | 3 | 1.861 |
| 0.3.0-current | 11/11 | 11 | 0 | 3 | 1.676 |

当前验证：
- `D:\python_project\pythonProject\bm-pack`
- 已通过：
  `.\.venv\Scripts\python.exe -m pytest -q`
- 当前结果：`25 passed`

重要文件：
- `src/cartonizer/solver.py`
  - 主求解流程。
  - `MAX_SKU_TYPES_CAP`
  - `Stage 1.5`
  - `Stage 1.6`
- `src/cartonizer/search.py`
  - 分箱评分函数。
- `src/cartonizer/optimizers.py`
  - 箱型优化和数量整形。
- `tools/export_erp_shipped_cases.py`
  - 从 ERP 导出已发货手工分箱样本。
  - 当前过滤：多箱、箱重 >= 12kg、单箱 SKU <= 6。
- `tests/test_erp_shipped_manual_cases.py`
  - ERP 样本回归测试。
  - 包含 #89 回归：4 箱且最大单箱 SKU <= 3。
- `D:\python_project\pythonProject\bm-cartonizer-benchmark\scripts\compare_versions.py`
  - 版本 benchmark。
- `D:\python_project\pythonProject\bm-cartonizer-benchmark\scripts\run_version.py`
  - 单版本运行器。

后续优化建议：
1. 不要先改 ERP 适配层。
2. 继续只在 `bm-pack` 和 benchmark 工程中优化。
3. 扩大有效样本：
   - 当前 ERP 符合条件样本只有 11 个。
   - 可以调整导出查询范围或确认历史数据是否缺失。
   - 不要放宽“多箱、箱重 >= 12kg、单箱 SKU <= 6”这三个核心样本规则，除非明确需要。
4. 继续优化 `Stage 1.6`：
   - 观察是否有其它样本可以在不增加箱数下进一步减少混装箱。
   - 避免引入指数级搜索；当前只适合小 SKU 数订单。
5. 如果未来要重新启用 3D 几何校验：
   - 先作为 advisory/warning，不要作为硬失败。
   - 当前几何校验会误杀手工可发的方案。

常用命令：

导出 ERP 样本：
```powershell
cd D:\python_project\pythonProject\bm-pack
.\.venv\Scripts\python.exe tools\export_erp_shipped_cases.py --limit 30 --scan-limit 500
```

同步样本到 benchmark：
```powershell
Copy-Item -Force D:\python_project\pythonProject\bm-pack\examples\erp_shipped_manual_cases.json D:\python_project\pythonProject\bm-cartonizer-benchmark\data\erp_shipped_manual_cases.json
```

运行 bm-pack 测试：
```powershell
cd D:\python_project\pythonProject\bm-pack
.\.venv\Scripts\python.exe -m pytest -q
```

运行版本对比：
```powershell
cd D:\python_project\pythonProject\bm-cartonizer-benchmark
py -3 scripts\compare_versions.py
```

约束：
- 不修改已发货 ERP 业务数据。
- 不回写历史分箱方案。
- 不删除 ERP 现有业务表。
- 暂时不修改 ERP `CartonizerAdapter.solve()` 的调用参数。
- 只在算法工程和 benchmark 工程中继续优化。
```

