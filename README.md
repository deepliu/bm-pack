
# Cartonizer（装箱求解器）

一个以“重量合规 + SKU尽量不混装”为核心目标的装箱求解器。

## 目标与约束
- 每箱重量必须满足 **12.0 kg ≤ weight ≤ 22.5 kg**（可配置）。
- 尽量保证同 SKU 装在一起；仅在修复 underweight 时才跨 SKU 混装。
- 不允许旋转（按固定朝向判断尺寸可放入）。
- 默认只做快速体积与尺寸过滤；可选 3D 校验。

## 输入与输出
输入格式与输出格式详见 `AGENTS.md` 的定义，保持稳定以便后续发布 PyPI。

## 运行命令
在项目根目录执行：

```powershell
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest -q

# 运行示例
python -m cartonizer.cli --input examples/order.json
# 可行性验证
python -m cartonizer.cli --input examples/bm_data.json --geometry-check --geometry-viz-dir output
```

### CLI 参数说明
- `--input`: 输入 JSON 路径（必填）。
- `--geometry-check`: 对每个箱执行 3D 几何校验（需要安装 `py3dbp`）。
- `--geometry-viz-dir`: 输出几何可视化文件的目录（可选）。

## 打包与发布（PyPI）

### 1) 构建本地包
```powershell
python -m build
```

### 2) 上传到 PyPI
为避免在命令行或文档中泄露 Token，推荐使用环境变量：
```powershell
$env:TWINE_USERNAME="__token__"
$env:TWINE_PASSWORD="<你的PyPI Token>"
python -m twine upload dist/*
```

如需上传到 TestPyPI：
```powershell
$env:TWINE_USERNAME="__token__"
$env:TWINE_PASSWORD="<你的TestPyPI Token>"
python -m twine upload --repository testpypi dist/*
```

## 分箱思路（详细版）

### 1) 可行性判定（重量区间）
订单总重为 W，箱数 B 需满足：
- `min_weight * B ≤ W ≤ max_weight * B`
推导：
- `B_min = ceil(W / max_weight)`
- `B_max = floor(W / min_weight)`
如果 `B_min > B_max`，直接判定 infeasible。

### 2) Stage A：利用率优先装箱（主解）
逐件装箱（不旋转），优先保证空间利用率接近目标（默认 0.8），其次尽量同 SKU：
1. **放入已有箱**：优先选择放入后能使利用率 ≥ 0.8 的箱；若需混装会有轻微惩罚。  
2. **新开箱选择箱型**：在满足单件尺寸/重量/体积的前提下，优先选择能让单件利用率接近目标的箱型。  
3. **重量硬约束**：任何箱不得超 `max_weight`，且总重包含 `tare_weight`。

### 3) Stage B：修复 underweight（< min_weight）
处理所有低于最小重量的箱：  
1. 轻箱合并（若合并后重量/体积均不超限）  
2. 从重箱搬小件到轻箱（保证 donor 仍 ≥ min_weight）  
3. 跨箱交换（swap）使两箱都落入区间  
优先同 SKU，再必要时跨 SKU。

### 4) 动态箱数与自动降级
若主解失败，会按顺序自动降级尝试：  
- 利用率目标：0.8 → 0.75 → 0.70 → 0.60  
- 体积阈值：必要时放宽到 `fill_rate=0.95`  
- 若仍失败，启用 **balanced 回退**：全局均衡分配以保证重量合规  

### 5) Stage C：几何可行性校验（可选）
默认仅做“尺寸 + 体积阈值”的快速过滤。  
若启用 `--geometry-check`，使用 `py3dbp` 做真实 3D 校验。  
**仅对最终方案进行 3D 验证与可视化输出**。

## 备注
- 当前策略不追求“箱数最少”，而是强调“重量合规 + SKU 聚合优先”。
- 若需要成本优化、体积利用率二级目标，可在后续版本扩展。
