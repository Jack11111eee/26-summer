"""Phase 2 wave 0：7:3 权重口径三落点回归测试（02-01，REF-5.7，SSOT §8.2，D-16）。

_compute_weights 直调风格（纯函数，items 用 list[dict] 直构，不必真插库）：
- Σhard weight == 0.7 / Σsoft == 0.3（±0.0005 尾差）；
- 纯 soft 岗位 Σweight == 1.0（大类归一，§8.2）；
- gate 项（experience/qualification）weight == 0.0，纯 gate 模型不除零（total_ratio==0 保护）；
- aggregation 总分公式只含 weight×(actual/5)×100，无 CATEGORY_RATIO 二次乘；
- config.CATEGORY_RATIO 枚举值 == SSOT §8.2 原文 0.7/0.3/0.0/0.0。

全程 LLM_PROVIDER=mock 离线运行；不触库的断言不插任何数据；不碰 data/app.db；
不 import 其他测试模块（单文件单进程纪律）。
运行：cd server && python -m pytest test_phase2_weights.py -v
"""
import inspect
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_weights.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import config  # noqa: E402
from server.services.aggregate import _compute_weights  # noqa: E402
import server.services.aggregation as aggregation_module  # noqa: E402

import server.services.aggregation  # noqa: E402


def _it(std_name: str, category: str, importance: str) -> dict:
    """直构 _compute_weights 输入项（category/importance 为其消费键）。"""
    return {"std_name": std_name, "category": category, "importance": importance}


def test_weight_73_hard_soft():
    """4 hard（importance 混合）+ 2 soft → Σhard == 0.7、Σsoft == 0.3（§8.2，±0.0005）。"""
    items = [
        _it("Python", "hard_skill", "required"),
        _it("MySQL", "hard_skill", "required"),
        _it("Redis", "hard_skill", "preferred"),
        _it("Docker", "hard_skill", "plus"),
        _it("沟通能力", "soft_skill", "required"),
        _it("协作能力", "soft_skill", "preferred"),
    ]
    _compute_weights(items)
    sum_hard = sum(it["weight"] for it in items if it["category"] == "hard_skill")
    sum_soft = sum(it["weight"] for it in items if it["category"] == "soft_skill")
    assert abs(sum_hard - 0.7) <= 0.0005, f"Σhard={sum_hard} 应 ≈0.7"
    assert abs(sum_soft - 0.3) <= 0.0005, f"Σsoft={sum_soft} 应 ≈0.3"


def test_weight_single_category():
    """纯 soft 岗位（只 soft items）Σweight == 1.0（大类归一，§8.2）。"""
    items = [
        _it("沟通能力", "soft_skill", "required"),
        _it("协作能力", "soft_skill", "preferred"),
        _it("抗压能力", "soft_skill", "plus"),
    ]
    _compute_weights(items)
    assert abs(sum(it["weight"] for it in items) - 1.0) <= 0.0005


def test_weight_gate_items_zero():
    """gate 项（experience/qualification）weight == 0.0；纯 gate 模型不除零且全 0（REF-5.7）。"""
    items = [
        _it("Python", "hard_skill", "required"),
        _it("沟通能力", "soft_skill", "preferred"),
        _it("后端开发经验", "experience", "required"),
        _it("本科学历", "qualification", "required"),
    ]
    _compute_weights(items)
    gate = [it for it in items if it["category"] in ("experience", "qualification")]
    non_gate = [it for it in items if it["category"] not in ("experience", "qualification")]
    for it in gate:
        assert it["weight"] == 0.0, f"gate 项 {it['std_name']} weight 应为 0.0，实得 {it['weight']}"
    # 非 gate 项不受 gate 类目出现的影响：Σ 仍为 1（7:3 在 hard/soft 间分配）
    assert abs(sum(it["weight"] for it in non_gate) - 1.0) <= 0.0005

    # 纯 gate 模型：7:3 下 experience/qualification 系数为 0 → total_ratio == 0
    # 原实现会 ZeroDivisionError 或把 drift=1.0 压给单个 gate item（weight=1.0 → 达标即 +100 分）
    pure_gate = [
        _it("后端开发经验", "experience", "required"),
        _it("本科学历", "qualification", "required"),
    ]
    _compute_weights(pure_gate)  # 不抛 ZeroDivisionError
    assert all(it["weight"] == 0.0 for it in pure_gate), \
        f"纯 gate 模型全部 weight 应为 0.0，实得 {[it['weight'] for it in pure_gate]}"


def test_aggregation_no_double_scaling():
    """总分公式只含 weight×(actual/5)×100，无 CATEGORY_RATIO 二次乘（§8.2）。"""
    src = inspect.getsource(aggregation_module)
    assert "actual / 5.0" in src  # :118-121 公式锚点在位
    assert "CATEGORY_RATIO" not in src, "aggregation.py 不得引入 CATEGORY_RATIO（二次乘违约）"


def test_enum_ratio_value():
    """config.CATEGORY_RATIO == SSOT §8.2 原文 0.7/0.3/0.0/0.0（四键保留）。"""
    assert config.CATEGORY_RATIO == {
        "hard_skill": 0.7,
        "soft_skill": 0.3,
        "experience": 0.0,
        "qualification": 0.0,
    }
