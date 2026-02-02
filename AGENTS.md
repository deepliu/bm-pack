# AGENTS.md — 装箱求解器项目（Cartonization Solver）

## 0. 项目目标
实现一个“装箱/装柜优化”求解器：
- 箱子：多种规格，长方体（内尺寸 L/W/H），可选箱自重。
- 产品：多种规格，长方体（L/W/H），重量不同，数量不同。
- 允许混装（一个箱可装多个 SKU），但**尽量保证同 SKU 装在一起**。
- 不允许旋转（只按固定朝向判断尺寸是否可放入）。
- 核心目标：**重量合规**，每箱总重必须满足 **12.0 kg ≤ weight ≤ 22.5 kg**（可配置）。

> 说明：这是组合优化问题（NP-hard），工程上采用“启发式 + 局部修复 + 可行性校验”的成熟路线，追求稳定、可解释、可扩展。

---

## 1. 输入输出规格（必须稳定，后续发布 PyPI 要兼容）

### 1.1 输入结构
- BoxType（箱型）
  - id: str
  - inner_L, inner_W, inner_H: float  (mm 或 cm，必须统一单位)
  - max_weight: float（默认 22.5）
  - min_weight: float（默认 12.0）
  - (optional) tare_weight: float（箱自重，默认 0）
  - (optional) cost: float（箱型成本，可用于二级目标）

- Item（产品/货品）
  - id: str（或 sku）
  - L, W, H: float
  - weight: float
  - qty: int

### 1.2 输出结构
PackingPlan（装箱方案）
- status: "ok" | "infeasible"
- reason: str（不可行时给原因）
- boxes: list[PackedBox]
  - box_type_id: str
  - total_weight: float
  - items: list[PackedItem]
    - item_id: str
    - qty: int
- metrics:
  - total_weight
  - box_count
  - lower_bound_by_weight = ceil(total_weight / max_weight)

---

## 2. 可行性判定（必须先做）
令订单总重为 W，箱数 B 必须满足：
- min_weight * B ≤ W ≤ max_weight * B

推导：
- B_min = ceil(W / max_weight)
- B_max = floor(W / min_weight)

若 B_min > B_max：
- 返回 infeasible（不可行），reason 包含 B_min/B_max/W 等关键数值。

---

## 3. 求解策略（分层求解，先按 SKU 分箱，再修复重量，再校验尺寸）

### Stage A：按 SKU 分箱（主解）
- 以 SKU 为单位逐个处理，优先形成“纯 SKU”箱。
- 对每个 SKU 选择能容纳单件的箱型：
  - 单件重量 ≤ max_weight
  - 单件体积 ≤ box_volume * fill_rate（默认 0.90）
  - 单件尺寸在固定朝向下可放入（不旋转）
- 以箱的重量上限与体积上限为约束，将该 SKU 直接分割成多箱。

### Stage B：修复 underweight（< min_weight）
- 处理所有 weight < min_weight 的箱：
  1) 两个轻箱尝试合并（<= max_weight 且体积快检通过）— 优先
  2) 从重箱搬“小件/轻件”到轻箱（保证 donor 箱搬走后仍 ≥ min_weight）
  3) 跨箱交换（swap）使两箱都落入区间
- **修复优先同 SKU**，只有必要时才跨 SKU 混装。

### Stage C：几何可行性校验（先占位接口，后续增强）
- 第 1 版不做真实 3D 坐标摆放，只做快速过滤。
- 预留 `geometry_validate(packed_box) -> bool` 接口，后续接入 3D 装箱启发式（极点法/层法等）。

---

## 4. 代码规范
- Python 3.10+（建议）
- 必须全量 type hints
- 核心领域对象使用 dataclasses（不可变/可序列化优先）
- 纯函数优先：同样输入必须给出稳定输出（如有随机，必须可设 seed）
- 不能引入重量级依赖（除非明确需要）
- 单元测试必须覆盖：可行、不可行、underweight 修复、上限 22.5 不超、边界值

---

## 5. 项目结构（建议）
- src/cartonizer/
  - __init__.py
  - types.py
  - feasibility.py
  - solver.py
  - repair.py
  - geometry.py
  - export.py
- tests/
  - test_feasibility.py
  - test_solver_basic.py
  - test_repair_underweight.py

---

## 6. 验收命令
- 安装开发依赖：`pip install -e ".[dev]"`
- 运行测试：`pytest -q`
- 运行示例：`python -m cartonizer.cli --input examples/order.json`

---

## 7. 版本迭代路线
- v0.1：Stage A + Stage B + 快速尺寸过滤（不做 3D 坐标）
- v0.2：引入真实 3D 装箱验证（可选依赖）
- v0.3：支持箱型成本/体积利用率二级目标、更多业务约束（易碎/不可同箱/分层等）
