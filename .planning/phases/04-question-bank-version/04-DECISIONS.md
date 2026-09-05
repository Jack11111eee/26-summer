# 04-DECISIONS.md — Phase 4 决策留痕

## 代确认记录（章程 §1/§4：auto 模式，事后留痕）

每条 = 日期时间 / 所在步骤 / 决定内容 / 依据。

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [04-001] | 2026-09-05 | discuss（auto） | D-47 model/version 绑定 = 填充既有列 + 消费侧收紧，不改表结构；equivalence_group_id/integrated_bindings_json 不落 | SSOT §9.2（列已在 Phase 2 `_migrate_question_bank_v2` 落）；REF-3.8/3.9 延后 |
| [04-002] | 2026-09-05 | discuss（auto） | D-48 升版语义 = 旧题 status 保持 active，靠消费侧 model_version 过滤 | SSOT §9.2「有效题目 = active 且 model/version 匹配」 |
| [04-003] | 2026-09-05 | discuss（auto） | D-49 幂等判重键升级 = (model_id, model_version, std_name, category, difficulty) | question_bank.py WR-03 判重现状 + v2 整链跳过风险 |
| [04-004] | 2026-09-05 | discuss（auto） | D-50 消费侧收紧点清单（readiness 3 处 + selection 1 处 + general 题同绑） | readiness.py / question_selection.py「版本近似」注释已预留收口点 |
| [04-005] | 2026-09-05 | discuss（auto） | D-51 生成失败可见 = readiness FAILED detail + admin todos 明细 | REF-8.4 + D-13「admin 页展示留 Phase 4」 |
| [04-006] | 2026-09-05 | discuss（auto） | D-52 GET /jds/orphan 声明前置 + WHERE position_id IS NULL | REF-7.1 + jds.py 参数路由吞掉实测 |
| [04-007] | 2026-09-05 | discuss（auto） | D-53 模型编辑校验强化（NaN/范围/类别/重复 std_name） | REF-7.2 + models.py ModelItem 现状 + competency_dict PK 对齐 |
| [04-008] | 2026-09-05 | discuss（auto） | D-54 item_id 落库 + rubric_version="v1"；measurement_target/evidence_requirement 留 NULL | SSOT §9.2 对齐 + Phase 5 证据链边界 |

## 边界/观察（非代确认，记档）

- **Phase 3 D-32 遗留**：experience/qualification 的 scope='general' 题仍被 generate_question_bank 生成（但 selection `category IN ('hard_skill','soft_skill')` 排除 + readiness 不算配额 → 生成但永不被选）。Phase 4 不扩大范围去删（D-32 收尾属 Phase 3 补漏），只确保 general 题生成时同绑 model_version。

## 开放参数（SSOT §31 类）

无。Phase 4 五 REF 均为结构性/缺陷修复项，不涉「参数待定」——不存在 §31 六项开放参数中的新增项。

## 硬关口 A 用户裁决（2026-09-05，已批准）

| ID | 步骤 | 决定 | 用户答复 |
|----|------|------|----------|
| [04-009] | 硬关口 A | orphan 列表字段口径 = **选项 B**（现有实现为准：字段子集 `jd_id/job_title/company/source_type/status/created_at` + `AND status != 'failed'`，与 get_todos 计数一致；非 D-52 字面全字段） | ① B |
| [04-010] | 硬关口 A | 前端「题库失败」展示卡 = **选项 A**（前端零破坏，本 phase 只做后端 `question_bank_failed` 明细，Positions.vue 零改动） | ② A |
| [04-011] | 硬关口 A | 13 文件回归面 = **选项 A**（并入 Phase 6 06-03 M1 回归 / 06-02 测试收口统一修种子，不追加 04-03） | ③ A |

**执行段锁定**：04-02 T2 的 orphan 查询按 [04-009] 选项 B 落地；04-01 的 todos 明细按 [04-010] 仅后端（`question_bank_not_ready` int + `question_bank_failed` list）；13 文件种子绑定不在本 phase 动，Phase 6 收口。
