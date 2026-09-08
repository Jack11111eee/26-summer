"""题库生成（07 §6.2）：模型 confirmed 后异步触发，仅生成岗位普通题（scope=position）。

- hard_skill / soft_skill → 岗位题库（scope=position，带难度链条）
- experience / qualification → 不生成题（SSOT §9.1 2026-09-07 裁决：两类只走 §16
  表单链采集；历史 scope=general 通用题为存量遗留，不迁移不删除）
幂等：同岗位同能力项已有 active 题则跳过，不重复生成。
"""
import json

from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.question_gen import QUESTION_GEN_SYSTEM, generate_questions_prompt


def _question_plan(item: dict) -> list[tuple[str, str]]:
    """按类目与权重规划 (difficulty, qtype) 清单（07 §6.2 + 难度递进 N1）。

    hard_skill：weight>10% → 3 档（easy/medium/hard），否则 2 档（easy/medium）
    soft_skill：2 档（easy/hard）
    experience/qualification：返回空清单——不生成题（SSOT §9.1 2026-09-07）
    """
    cat = item["category"]
    if cat == "hard_skill":
        if (item.get("weight") or 0) > 0.10:
            return [("easy", "objective"), ("medium", "subjective"), ("hard", "subjective")]
        return [("easy", "objective"), ("medium", "subjective")]
    if cat == "soft_skill":
        return [("easy", "subjective"), ("hard", "subjective")]
    return []  # experience/qualification：走表单链，不生成题


def _as_text(value: str | list | None, sep: str) -> str | None:
    """LLM 产出形态归一化（2026-09-08，qbt_74fedfff3a23 故障）。

    question_gen 的 SYSTEM JSON 模板声明 rubric 为字符串，出题要求又写「rubric 给
    3~5 条可观察的评分要点」——LLM 合理返回 list[str]，而 sqlite3 参数绑定不支持
    list 直插 TEXT 列（Error binding parameter 14）。prompt 不动（产出质量良好），
    在 CR-01/WR-06 判断之前把 rubric/answer_key 归一为 str，后续 .strip() 全部安全：
    - str 原样返回；None → None；
    - list → 过滤非空字符串元素后 join（rubric 用 \n 每条一行，answer_key 用 |
      ——scoring._looks_like_regex 认 | 为分支，与实测 answer_key 形态一致）；
    - 其余标量 → str(value)；全空 list → None（与 LLM 返回 null 的空值语义一致）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [p for p in value if isinstance(p, str) and p.strip()]
        return sep.join(parts) if parts else None
    return str(value)


def _mock_question_gen(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：从 user prompt 中解析能力项/难度/题型，生成模板题。"""
    lines = dict(
        ln.split("：", 1) for ln in user_prompt.splitlines() if "：" in ln
    )
    std_name = lines.get("能力项", "该能力")
    last = user_prompt.strip().splitlines()[-1]
    difficulty = "medium"
    for d in ("easy", "medium", "hard"):
        if f" {d} " in last:
            difficulty = d
            break
    qtype = "objective" if " objective " in last else "subjective"

    if difficulty == "easy":
        stem = f"请谈谈你对{std_name}的理解。"
    else:
        stem = f"请描述一个使用{std_name}解决复杂问题的场景。"
    q = {"stem": stem, "difficulty": difficulty, "qtype": qtype,
         "answer_key": std_name if qtype == "objective" else None,
         "rubric": None if qtype == "objective" else f"能结合实例说明{std_name}的应用；思路清晰；有结果数据"}
    return {"questions": [q]}


def _insert_question(conn, *, scope: str, position_id: str | None, item: dict,
                     difficulty: str | None, qtype: str, stem: str,
                     answer_key: str | None, rubric: str | None,
                     chain_key: str | None, chain_seq: int | None,
                     model_id: str, model_version: int | None, item_id: str | None) -> None:
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version, item_id, rubric_version,"
        " std_name, category, difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
        " source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), scope, position_id, model_id, model_version, item_id, "v1",
         item["std_name"], item["category"],
         difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,
         "llm_seed", "active", now_iso()),
    )


def _update_task_status(conn, position_id: str, model_id: str, task_status: str,
                        error_msg: str | None = None) -> None:
    """更新该 (position, model) 最新 task 行状态（D-12：RUNNING/SUCCEEDED/FAILED 自维护）。

    WR-12：finished_at 的 CASE 补 ELSE finished_at——否则非终态更新（如 retry 后的
    RUNNING）会把已终态行的 finished_at 抹成 NULL；排序补 rowid DESC 作 created_at
    并列时的 tie-break，与 started_at 的 COALESCE 保护对称。
    """
    conn.execute(
        "UPDATE question_bank_task SET status=?, started_at=COALESCE(started_at, CASE ? WHEN 'RUNNING' THEN ? END),"
        " finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ? ELSE finished_at END, error_msg=?"
        " WHERE task_id=(SELECT task_id FROM question_bank_task"
        " WHERE position_id=? AND model_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1)",
        (task_status, task_status, now_iso(), task_status, now_iso(), error_msg,
         position_id, model_id),
    )


def _update_task_progress(conn, position_id: str, model_id: str, *,
                          total: int | None = None) -> None:
    """循环前写 total（§9.5）：(item × 难度档) 总数，跳过 exp/qual 项。"""
    conn.execute(
        "UPDATE question_bank_task SET total=?"
        " WHERE task_id=(SELECT task_id FROM question_bank_task"
        " WHERE position_id=? AND model_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1)",
        (total, position_id, model_id),
    )


def _advance_task_progress(conn, position_id: str, model_id: str,
                           done: int, current_item: str) -> None:
    """循环内逐档推进 done/current_item（§9.5）+ 立即 commit。

    与 aggregate_task._advance 同型：UPDATE+commit 必须原子——update 后本连接
    若持未决写事务进入 LLM 调用，llm_trace 落库的独立连接会撞 5s busy_timeout
    （database is locked，§8.4 已论证同型问题）；逐次 commit 也让轮询侧连接
    不长持锁。done 含幂等跳过的档（查重命中的档也算已处理）。
    """
    conn.execute(
        "UPDATE question_bank_task SET done=?, current_item=?"
        " WHERE task_id=(SELECT task_id FROM question_bank_task"
        " WHERE position_id=? AND model_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1)",
        (done, current_item, position_id, model_id),
    )
    conn.commit()


def archive_superseded_banks(conn, position_id: str) -> None:
    """旧版题库归档（SSOT §9.2，2026-09-08）：该岗位被更新 confirmed 模型取代的
    旧版题库行 status='active' → 'archived'（保留行支撑追溯，不删数据）。

    谓词：岗位全部 confirmed 模型 − 最新行（version 高者为新，同 version 取 rowid
    最新——与 assessment._latest_confirmed_model 同口径）名下的 active 题；
    在途豁免——model_id 被 in_progress 会话引用的不动（动态派题不断粮；豁免只认
    in_progress：已终态会话的追溯按 bank_question_id 直连 join，不依赖 active）。
    不 commit（D-06 契约：事务边界由调用方持有——confirm 事务 / 会话终态补刀各在
    既有 commit 内顺带落库）。eval_seed 行（谓词 status='active'）天然不被触碰；
    draft/stalled 模型名下无 active 题，谓词同样天然覆盖。
    """
    keep = conn.execute(
        "SELECT model_id FROM competency_model"
        " WHERE position_id=? AND status='confirmed'"
        " ORDER BY version DESC, rowid DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if keep is None:
        return  # 该岗位无 confirmed 模型：无可判定「被取代」，不动任何行
    conn.execute(
        "UPDATE question_bank SET status='archived' WHERE status='active'"
        " AND model_id IN (SELECT model_id FROM competency_model"
        "                  WHERE position_id=? AND status='confirmed' AND model_id != ?)"
        " AND model_id NOT IN (SELECT DISTINCT model_id FROM assessment_session"
        "                      WHERE status='in_progress')",
        (position_id, keep["model_id"]),
    )


def generate_question_bank(position_id: str, model_id: str) -> None:
    """为 confirmed 模型生成题库（异步任务调用）。失败不抛（可手动重触发），但落表 FAILED。

    task 行生命周期（D-12）：入口置 RUNNING / 岗位不存在置 FAILED /
    正常完成置 SUCCEEDED / 异常置 FAILED + error_msg（"失败静默改为至少落表"）。
    进度列（§9.5）：循环前写 total；循环内逐档更新 done/current_item 并与该档题目
    写入同事务 commit——done 含幂等跳过的档。
    """
    conn = get_conn()
    try:
        pos = conn.execute("SELECT name FROM position WHERE position_id=?", (position_id,)).fetchone()
        if pos is None:
            _update_task_status(conn, position_id, model_id, "FAILED", error_msg="岗位不存在")
            conn.commit()
            return
        model_row = conn.execute(
            "SELECT version FROM competency_model WHERE model_id=?", (model_id,)
        ).fetchone()
        model_version = model_row["version"] if model_row else None
        _update_task_status(conn, position_id, model_id, "RUNNING")
        conn.commit()
        position_name = pos["name"]
        items = conn.execute(
            "SELECT item_id, std_name, category, required_level, weight, evidence_json"
            " FROM competency_item WHERE model_id=?",
            (model_id,),
        ).fetchall()

        # 先收集待生成 item（含计划档），跳过 exp/qual 项（SSOT §9.1：不生成题）
        planned: list[dict] = []
        for row in items:
            item = dict(row)
            if item["category"] not in ("hard_skill", "soft_skill"):
                continue
            # §8.5 防御过滤：正常链路落库证据不含 excluded 条目（PUT 剥离/聚合滤除），
            # 此处兜底旧版本快照或手工改库——question_gen 岗位背景取第一条未排除证据
            item["evidence"] = [
                ev for ev in json.loads(item.pop("evidence_json") or "[]")
                if not (isinstance(ev, dict) and ev.get("excluded"))
            ]
            planned.append(item)

        # 进度起点（§9.5）：total = Σlen(plan)（跳过 exp/qual 后——与循环实际处理的档数一致）
        _update_task_progress(conn, position_id, model_id,
                              total=sum(len(_question_plan(it)) for it in planned))
        conn.commit()
        done = 0
        for item in planned:
            plan = _question_plan(item)
            chain_key = item["item_id"] if len(plan) > 1 else None
            for seq, (difficulty, qtype) in enumerate(plan, start=1):
                current = f"({item['std_name']}, {item['category']}, {difficulty})"
                _advance_task_progress(conn, position_id, model_id, done, current)
                # WR-03：幂等按 (std_name, category, difficulty) 的 plan 目标粒度——
                # 部分 item 成功的链条重触发时只补缺档（easy 有/medium missing 只生成
                # medium），不再整 item 跳过导致残缺链条永不补齐
                exists = conn.execute(
                    "SELECT 1 FROM question_bank WHERE scope='position'"
                    " AND model_id=? AND model_version=?"
                    " AND std_name=? AND category=? AND difficulty=?"
                    " AND status='active' LIMIT 1",
                    (model_id, model_version, item["std_name"], item["category"], difficulty),
                ).fetchone()
                if exists:
                    # §9.5：查重命中的档也算已处理（done 含幂等跳过的档）
                    done += 1
                    _advance_task_progress(conn, position_id, model_id, done, current)
                    continue
                result = call_llm_json(
                    "question_gen", item["item_id"], QUESTION_GEN_SYSTEM,
                    generate_questions_prompt(item, position_name, difficulty or "general", qtype),
                    mock_fn=_mock_question_gen,
                )
                for q in result.get("questions", []):
                    # 2026-09-08 归一化先于 CR-01：LLM 可能返回 list[str]（见 _as_text），
                    # 之后的 .strip()/入库消费全部按 str 处理
                    q_rubric = _as_text(q.get("rubric"), "\n")
                    q_answer_key = _as_text(q.get("answer_key"), "|")
                    # CR-01：objective 题缺 answer_key 时降级为 subjective（rubric 兜底），
                    # 阻断"无 answer_key 客观题入库后空正则恒命中"的评分缺陷
                    q_qtype = q.get("qtype", qtype)
                    if q_qtype == "objective" and not (q_answer_key or "").strip():
                        q_qtype = "subjective"
                        q_answer_key = None
                        # WR-06：降级后的主观题需 rubric 判据——LLM 可能 answer_key/rubric
                        # 均为空，此时补默认 rubric，避免主观评分缺判据
                        if not (q_rubric or "").strip():
                            q_rubric = f"能结合实例说明{item['std_name']}的应用；思路清晰；有结果数据"
                    _insert_question(
                        conn, scope="position",
                        position_id=position_id,
                        item=item, difficulty=difficulty, qtype=q_qtype,
                        stem=q["stem"], answer_key=q_answer_key, rubric=q_rubric,
                        chain_key=chain_key, chain_seq=seq if chain_key else None,
                        model_id=model_id, model_version=model_version, item_id=item["item_id"],
                    )
                done += 1
                # 与该档题目写入同事务 commit（§9.5）：done/current_item 与题目原子落库
                _advance_task_progress(conn, position_id, model_id, done, current)
        _update_task_status(conn, position_id, model_id, "SUCCEEDED")
        conn.commit()
    except Exception as e:  # noqa: BLE001
        # 失败不抛（保持"可手动重触发"总语义），但至少落表 FAILED（D-12）；
        # error_msg 截断 2000（§9.5：排障需完整异常文本；200 会截断 sqlite/python 原文）
        try:
            _update_task_status(conn, position_id, model_id, "FAILED", error_msg=str(e)[:2000])
            conn.commit()
        except Exception:  # noqa: BLE001
            pass  # 落表本身失败时维持旧静默语义（无更好降级路径）
    finally:
        conn.close()  # WR-05：后台任务反复触发（含 retry），不 close 会逐步耗尽连接
