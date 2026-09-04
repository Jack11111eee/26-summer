"""Phase 2 难度路径状态机测试（REF-4.2——SSOT §11.2 全判据）。

- next_difficulty 纯函数表驱动判据：升（easy→medium 一次充分 / medium→hard 充分且稳定
  + 仅 required_level>4）/ 降（同难度连续两道未达锚点 / followup 后仍模糊；easy 不降）/
  恢复滞回（连续两次充分或一次稳定）/ 跳级禁止（easy→hard 直迁不可产生）
- 七类排除（is_valid_failure=False 不累计 fail 计数——§11.2「不计入普通失败」）
- 一次实例内不升降级（状态机只在封存点调用——本文件以「函数由调用点约束」间接覆盖）
- 集成：答题封存后 DIFFICULTY_LOWERED 事件 payload 四键（criterion/evidence_counts/
  from_difficulty/to_difficulty）+ 快照同事务（最新封存实例行的 snapshot
  current_difficulty == 事件 to_state）
- 选题层承接：item 有 snapshot(current_difficulty=medium) → 下一实例 difficulty='medium'

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_phase2_difficulty.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_difficulty.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.difficulty import next_difficulty, update_path_state  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- 纯函数表驱动（§11.2 逐判据一行） ----------

def _make_snap(**kw) -> dict:
    """SNAPSHOT 默认值（<interfaces> 七键——D-20 Claude's Discretion 建议形态）。"""
    snap = {
        "item_id": "c_test",
        "current_difficulty": "easy",
        "sufficient_in_row": 0,
        "stable_ever": False,
        "fail_same_difficulty": 0,
        "followup_ambiguous": False,
        "exception_used": False,
    }
    snap.update(kw)
    return snap


def test_easy_to_medium_one_sufficient():
    """easy + 一次充分证据（sufficient_in_row≥1）→ ("medium", DIFFICULTY_RAISED)。"""
    new_d, ev = next_difficulty(_make_snap(current_difficulty="easy", sufficient_in_row=1),
                                evidence_sufficient=True, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d == "medium" and ev == "DIFFICULTY_RAISED", f"实得 {(new_d, ev)}"


def test_medium_to_hard_requires_stable_and_level():
    """medium→hard：充分且稳定 + required_level>4；level=4 无迁移。"""
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", sufficient_in_row=1,
                                           stable_ever=True),
                                evidence_sufficient=True, stable_evidence=True,
                                is_valid_failure=True, required_level=5)
    assert new_d == "hard" and ev == "DIFFICULTY_RAISED", f"level=5 应升 hard，实得 {(new_d, ev)}"
    # required_level=4 不满足 >4 门槛 → 无迁移
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", sufficient_in_row=1,
                                           stable_ever=True),
                                evidence_sufficient=True, stable_evidence=True,
                                is_valid_failure=True, required_level=4)
    assert new_d is None and ev is None, f"level=4 不应升 hard，实得 {(new_d, ev)}"
    # 充分但不稳定 → 无迁移
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", sufficient_in_row=1,
                                           stable_ever=False),
                                evidence_sufficient=True, stable_evidence=False,
                                is_valid_failure=True, required_level=5)
    assert new_d is None and ev is None, f"不稳定不应升 hard，实得 {(new_d, ev)}"


def test_downgrade_two_consecutive_failures():
    """medium 且同难度连续两道有效题未达锚点 → ("easy", DIFFICULTY_LOWERED)；easy 不降。"""
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", fail_same_difficulty=2),
                                evidence_sufficient=False, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d == "easy" and ev == "DIFFICULTY_LOWERED", f"实得 {(new_d, ev)}"
    # easy 是最低难度——不可降级
    new_d, ev = next_difficulty(_make_snap(current_difficulty="easy", fail_same_difficulty=2),
                                evidence_sufficient=False, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d is None and ev is None, f"easy 不应降级，实得 {(new_d, ev)}"
    # 只有一次失败（fail=1）不触发
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", fail_same_difficulty=1),
                                evidence_sufficient=False, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d is None and ev is None, f"fail=1 不应降级，实得 {(new_d, ev)}"


def test_downgrade_followup_ambiguous():
    """medium 且 followup 后仍模糊 → ("easy", DIFFICULTY_LOWERED)。"""
    new_d, ev = next_difficulty(_make_snap(current_difficulty="medium", followup_ambiguous=True),
                                evidence_sufficient=False, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d == "easy" and ev == "DIFFICULTY_LOWERED", f"实得 {(new_d, ev)}"


def test_invalid_failure_not_counted():
    """is_valid_failure=False（七类排除）→ 未达锚点不计入 fail 计数。"""
    from server.services.difficulty import advance_snapshot
    # 有效失败 → fail +1
    snap = advance_snapshot(_make_snap(), evidence_sufficient=False, stable_evidence=False,
                            is_valid_failure=True, followup_ambiguous=False)
    assert snap["fail_same_difficulty"] == 1, "有效失败应累计 fail"
    # 无效失败（七类）→ fail 不增
    snap = advance_snapshot(_make_snap(fail_same_difficulty=1), evidence_sufficient=False,
                            stable_evidence=False, is_valid_failure=False,
                            followup_ambiguous=False)
    assert snap["fail_same_difficulty"] == 1, "七类排除不得累计 fail 计数（§11.2 原文）"
    # 充分证据 → sufficient_in_row +1 且 fail 清零
    snap = advance_snapshot(_make_snap(fail_same_difficulty=2), evidence_sufficient=True,
                            stable_evidence=True, is_valid_failure=True,
                            followup_ambiguous=False)
    assert snap["sufficient_in_row"] == 1 and snap["fail_same_difficulty"] == 0, \
        f"充分应清 fail 且 sufficient+1，实得 {snap}"
    assert snap["stable_ever"] is True, "稳定证据出现即置 stable_ever"


def test_restore_hysteresis():
    """降级后恢复滞回：连续两次充分（sufficient_in_row≥2）或一次稳定（stable_ever）→ RESTORED。"""
    new_d, ev = next_difficulty(_make_snap(current_difficulty="easy", sufficient_in_row=2),
                                evidence_sufficient=True, stable_evidence=False,
                                is_valid_failure=True, required_level=3)
    assert new_d == "medium" and ev == "DIFFICULTY_RESTORED", \
        f"两次充分应恢复，实得 {(new_d, ev)}"
    # 一次稳定（stable_ever=True 且 sufficient_in_row=1）→ 同样恢复
    new_d, ev = next_difficulty(_make_snap(current_difficulty="easy", sufficient_in_row=1,
                                           stable_ever=True),
                                evidence_sufficient=True, stable_evidence=True,
                                is_valid_failure=True, required_level=3)
    assert new_d == "medium" and ev == "DIFFICULTY_RESTORED", \
        f"一次稳定应恢复，实得 {(new_d, ev)}"


def test_no_skip_within_instance():
    """跳级禁止表驱动组合抽查：easy 输入加 stable/sufficient 各态均得 medium 或 None，永不 hard。"""
    cases = [
        # (sufficient_in_row, stable_ever, evidence_sufficient, stable_evidence)
        (1, False, True, False),
        (1, True, True, True),
        (2, True, True, True),
        (3, False, True, False),
        (0, False, False, False),
        (1, False, False, False),
    ]
    for s_in_row, s_ever, ev_suf, ev_stable in cases:
        new_d, ev = next_difficulty(
            _make_snap(current_difficulty="easy", sufficient_in_row=s_in_row,
                       stable_ever=s_ever),
            evidence_sufficient=ev_suf, stable_evidence=ev_stable,
            is_valid_failure=True, required_level=5)
        assert new_d in ("medium", None), \
            f"easy 输入 ({s_in_row},{s_ever},{ev_suf},{ev_stable}) 不得直迁 hard，实得 {new_d}"
        if new_d == "medium":
            assert ev in ("DIFFICULTY_RAISED", "DIFFICULTY_RESTORED")


def test_path_unavailable_event():
    """跳级禁止：函数对跨档非法迁移无输出路径——不产生 easy→hard 直迁（标记不静默语义的
    边界测试：函数返回 None 即无迁移，非法配置下由 PATH_UNAVAILABLE 事件承载——本 phase
    跳级直接不实现，函数唯一不可能返回的迁移对即断言之）。"""
    # easy + 任何充分/稳定组合 + 任意 required_level —— 函数永不返回 "hard"
    for ev_suf in (True, False):
        for ev_stable in (True, False):
            for s_in_row in (0, 1, 2, 3):
                for s_ever in (True, False):
                    new_d, _ev = next_difficulty(
                        _make_snap(current_difficulty="easy", sufficient_in_row=s_in_row,
                                   stable_ever=s_ever),
                        evidence_sufficient=ev_suf, stable_evidence=ev_stable,
                        is_valid_failure=True, required_level=5)
                    assert new_d != "hard", \
                        f"easy→hard 直迁不可产生（跳级禁止），输入 {ev_suf}/{ev_stable}/{s_in_row}/{s_ever}"


# ---------- CR-02 回归：跨难度迁移清档内计数（换档即换「同难度」分母） ----------

def _cr02_seed_refs() -> None:
    """直插 user/position/competency_model/question_bank 引用行（外键依赖）。"""
    conn = get_conn()
    now = now_iso()
    conn.execute("INSERT OR IGNORE INTO user(user_id, username, password_hash, role, created_at)"
                 " VALUES(?,?,?,?,?)", ("u_cr02", "u_cr02", "x", "candidate", now))
    conn.execute("INSERT OR IGNORE INTO position(position_id, name, status, created_at)"
                 " VALUES(?,?,?,?)", ("p_cr02", "CR-02 岗位", "active", now))
    conn.execute(
        "INSERT OR IGNORE INTO competency_model(model_id, position_id, version, status,"
        " model_json, created_at) VALUES(?,?,?,?,?,?)",
        ("m_cr02", "p_cr02", 1, "confirmed", "{}", now))
    conn.execute(
        "INSERT OR IGNORE INTO question_bank(question_id, scope, position_id, std_name,"
        " category, difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("qb_cr02", "position", "p_cr02", "CR-02 std", "hard_skill", "medium",
         "subjective", "CR-02 占位题", None, "判据", "human", "active", now))
    conn.commit()
    conn.close()


def _cr02_new_session(sid: str) -> None:
    """建一条外键自洽的会话行（CR-02 直测 update_path_state 用，不走 API）。"""
    _cr02_seed_refs()
    conn = get_conn()
    now = now_iso()
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, "u_cr02", "p_cr02", "m_cr02", 1, "in_progress", now, now))
    conn.commit()
    conn.close()


def _cr02_seal(sid: str, seq: int, pre_snap: dict | None, obs: dict) -> str:
    """插入前置封实行（载 pre_snap）+ 本封存实例并推进状态机，返回本实例 question_id。

    update_path_state 读「除本实例外最新的封存行」——pre_snap 写在 seq 行、本实例为
    seq+1 行（同 session seq 单调递增保证读到 pre_snap 指定行）；pre_snap=None 视作
    该 item 首封存（无前置行——update_path_state 初始 easy）。本实例行初值不带
    snapshot（由 update_path_state 写入）。bank 引用共享 qb_cr02。
    """
    conn = get_conn()
    now = now_iso()
    if pre_snap is not None:
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " question_type, item_id, status, path_state_snapshot, closed_at, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (new_id("aq"), sid, "qb_cr02", seq, "ordinary", "item_cr02", "sealed",
             json.dumps(pre_snap, ensure_ascii=False), now, now))
    qid = new_id("aq")
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
        " question_type, item_id, status, path_state_snapshot, closed_at, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (qid, sid, "qb_cr02", seq + 1, "ordinary", "item_cr02", "sealed",
         None, now, now))
    conn.commit()
    update_path_state(conn, session_id=sid, item_id="item_cr02",
                      sealed_question_id=qid, observation=obs, required_level=3)
    conn.commit()
    conn.close()
    return qid


def _cr02_latest_snap(sid: str) -> dict:
    """会话【最后插入】实例行的 snapshot（MAX(rowid)——插入序，与 seq 取值无关）。"""
    rows = _q("SELECT path_state_snapshot FROM assessment_question"
             " WHERE session_id=? AND rowid=(SELECT MAX(rowid) FROM assessment_question"
             " WHERE session_id=?)", (sid, sid))
    return json.loads(rows[0]["path_state_snapshot"])


def test_migration_resets_counters_table_driven():
    """update_path_state 迁移段表驱动：迁移后 snapshot 的 fail_same_difficulty=0、
    followup_ambiguous=False；降 easy 时 sufficient_in_row=0（CR-02 坏序列防回归）。"""
    # 表驱动：每 case 组装「迁移触发前的 snapshot 形态」落为上一封存行，直接调
    # update_path_state 后断言新 snapshot 计数器清零（持 conn 的 DB 集成路）。
    # case: (名, 前置 snapshot, 本封存 observation, 期望迁移 level 或 None)
    cases = [
        # medium fail=2 → 降 easy：fail 清零（旧代码带 fail=2 落 easy 档残留）
        ("medium-fail2-lower", _make_snap(current_difficulty="medium", fail_same_difficulty=2),
         {"evidence_sufficient": False, "is_valid_failure": True}, "easy"),
        # medium fail=1 + followup_ambiguous=True → 降 easy（判据 2 触发）：ambiguous 清零
        ("medium-famb-lower", _make_snap(current_difficulty="medium", fail_same_difficulty=1,
                                         followup_ambiguous=True),
         {"evidence_sufficient": False, "is_valid_failure": True}, "easy"),
        # easy 两次充分 → 升 medium：迁移动作存在（升档无 sufficient 清零——仅降 easy 适用）
        ("easy-raise", _make_snap(current_difficulty="easy", sufficient_in_row=2),
         {"evidence_sufficient": True, "is_valid_failure": True}, "medium"),
        # 无迁移：计数器照常推进（对照——迁移清理不误伤无迁移路径；fail 起 0，
        # 推进到 1 即普通一次失败——起 1 会推到 2 直接触发降级，不成为对照）
        ("medium-no-migration", _make_snap(current_difficulty="medium", fail_same_difficulty=0),
         {"evidence_sufficient": False, "is_valid_failure": True}, None),
    ]
    for name, pre_snap, obs, exp_level in cases:
        sid = new_id("sess")
        _cr02_new_session(sid)
        _cr02_seal(sid, 1, pre_snap, obs)
        snap = _cr02_latest_snap(sid)
        if exp_level is not None:
            assert snap["current_difficulty"] == exp_level, \
                f"{name}: 期望迁移到 {exp_level}，实得 {snap}"
            assert snap["fail_same_difficulty"] == 0, \
                f"{name}: 迁移后 fail_same_difficulty 应清零（换档换分母），实得 {snap}"
            assert snap["followup_ambiguous"] is False, \
                f"{name}: 迁移后 followup_ambiguous 应清零（判据 2 不跨档携带），实得 {snap}"
            if exp_level == "easy":
                assert snap["sufficient_in_row"] == 0, \
                    f"{name}: 降 easy 后 sufficient_in_row 应清零（滞回按新档累计），实得 {snap}"
        else:
            assert snap["fail_same_difficulty"] == 1, \
                f"{name}: 无迁移路径 fail 计数照常推进（对照），实得 {snap}"
            assert snap["current_difficulty"] == "medium", f"{name}: 对照例不应迁移，实得 {snap}"


def test_residual_followup_ambiguous_not_carried_after_migration():
    """CR-02 残留计数可达坏序列（hard→medium 迁移路）：hard 因 followup_ambiguous
    降级 medium → medium 一道七类排除（is_valid_failure=False）+ 一次普通失败——
    不得再触发降级（旧代码：迁移不清 followup_ambiguous，残留 True 在下一次任何
    封存即直接第二次降级，连七类排除这种非候选人源性观察也触发——双重违反 §11.2）。

    注：报告原文场景 3 的 medium→easy→升回 medium 序列在 advance_snapshot 的
    「充分证据清 famb」下自愈（升回必经充分证据）——可达的残留触发路是本测试的
    hard→medium 路（迁移后无需充分证据即可再次封存触发）。
    """
    sid = new_id("sess")
    _cr02_new_session(sid)

    # ① hard 档 followup_ambiguous=True → 降级 medium（DIFFICULTY_LOWERED）
    _cr02_seal(sid, 1, _make_snap(current_difficulty="hard", followup_ambiguous=True),
               {"evidence_sufficient": False, "is_valid_failure": True})
    lowered = _q("SELECT to_state FROM assessment_state_event WHERE session_id=?"
                 " AND event_type='DIFFICULTY_LOWERED'", (sid,))
    assert lowered, "hard followup_ambiguous 应触发降级（前置条件）"
    assert lowered[-1]["to_state"] == "medium"

    # ② medium 一道七类排除封存（MODEL_UNCERTAIN，is_valid_failure=False）：
    #    两计数器不动、不得迁移/降级
    snap_med = _cr02_latest_snap(sid)
    assert snap_med["current_difficulty"] == "medium", snap_med
    _cr02_seal(sid, 3, snap_med,
               {"answer_state": "MODEL_UNCERTAIN", "evidence_sufficient": False,
                "is_valid_failure": False})
    snap2 = _cr02_latest_snap(sid)
    assert snap2["current_difficulty"] == "medium", \
        f"七类排除不得迁移/降级（is_valid_failure=False），实得 {snap2}"

    # ③ medium 一次普通失败（fail=1 < 2，famb 应已清零）→ 不得降级：
    #    降级事件计数应仍为 1（只有 ① 那一次）
    _cr02_seal(sid, 5, snap2,
               {"evidence_sufficient": False, "is_valid_failure": True,
                "followup_ambiguous": False})
    all_lowered = _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=?"
                     " AND event_type='DIFFICULTY_LOWERED'", (sid,))
    assert all_lowered[0]["c"] == 1, \
        "迁移后残留 followup_ambiguous 不得在后续封存触发降级（换档即换分母），" \
        f"实得 {all_lowered[0]['c']} 次降级"


# ---------- 集成（事件 payload + 快照同事务 + 选题承接） ----------

def _seed_position_with_confirmed_model(required_level: int = 3) -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（单 required hard item）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "难度状态机工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.4},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.3},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], required_level,
             it["importance"], it["weight"], 0),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str) -> None:
    """岗位题：Python easy/medium/hard 各 2（降级/承接测试需同 item 多实例）+ 其余配额。"""
    conn = get_conn()
    now = now_iso()

    def _add(std_name, category, difficulty):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, std_name, category, difficulty, "subjective",
             f"{std_name} {difficulty} 题", None, "判据", None, None, "human", "active", now),
        )

    # Python：easy×2 / medium×2 / hard×2（同 item 多实例——难度路径测试主体）
    for d in ("easy", "easy", "medium", "medium", "hard", "hard"):
        _add("Python", "hard_skill", d)
    # MySQL hard_skill 补足配额（easy/medium/hard）
    for d in ("easy", "medium"):
        _add("MySQL", "hard_skill", d)
    # soft_skill：沟通能力 easy/medium/hard
    for d in ("easy", "medium", "hard"):
        _add("沟通能力", "soft_skill", d)
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p2_diff_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# 长但空的答案（>20 字 + 无 _EVIDENCE_WORDS）→ followup 后仍模糊 → 有效失败
_LONG_EMPTY = (
    "这个问题嘛，我觉得总体上来说还是挺有说道的地方的，"
    "不过当时的情况也是比较复杂的，各色各样的因素交织在一起。"
)
# 充分证据答案（含 项目/数据/负责 实义词）
_EVIDENCE = (
    "我在电商平台项目中负责订单模块重构，通过拆分大事务重构数据表结构，"
    "把下单接口的响应时间从数据上看降低了一半，并复盘成文档沉淀给团队。"
)


def _cur_q(sid: str, headers: dict) -> dict | None:
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["current_question"]


def _answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": question_id, "answer": answer}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_events_payload_and_same_transaction():
    """item 先升到 medium（充分证据）再连续两道低分（followup 后强制 next，有效失败）
    → 封存后 DIFFICULTY_LOWERED：payload 四键（criterion/evidence_counts/from/to）+
    最新封存实例行 snapshot current_difficulty == 事件 to_state（§13.1 同事务）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_diff_lower")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 答 1 题（充分证据 → easy→medium 升级）锁定 target item
    cur = _cur_q(sid, headers)
    assert cur is not None
    _answer(sid, headers, cur["question_id"], _EVIDENCE)
    raised = _q(
        "SELECT assessment_question_id FROM assessment_state_event"
        " WHERE session_id=? AND event_type='DIFFICULTY_RAISED'", (sid,))
    assert raised, "一次充分证据应触发 easy→medium（DIFFICULTY_RAISED）"
    item_id = _q("SELECT item_id FROM assessment_question WHERE question_id=?",
                 (raised[0]["assessment_question_id"],))[0]["item_id"]
    assert item_id, "升级行须挂 item_id"

    # 该 item 后续两实例均长但空（followup×2 后强制 next = 封存 = 有效失败）
    fails_on_item = 0
    lowered = None
    for _ in range(20):
        evs = _q(
            "SELECT event_type FROM assessment_state_event WHERE session_id=?"
            " AND event_type='DIFFICULTY_LOWERED'", (sid,))
        if evs:
            lowered = evs[0]
            break
        cur = _cur_q(sid, headers)
        if cur is None:
            break
        # 该 item 的实例只上不充分答案；其他 item 保持沉默推进
        row = _q("SELECT item_id FROM assessment_question WHERE question_id=?",
                 (cur["question_id"],))[0]
        if row["item_id"] == item_id:
            resp = _answer(sid, headers, cur["question_id"], _LONG_EMPTY)
            n_followups = 1
            while resp["action"] == "followup" and n_followups < 3:
                resp = _answer(sid, headers, cur["question_id"], _LONG_EMPTY)
                n_followups += 1
            fails_on_item += 1
        else:
            _answer(sid, headers, cur["question_id"], _EVIDENCE)
    assert lowered is not None, \
        f"medium 两连有效失败应触发 DIFFICULTY_LOWERED（关联 item fail 计 {fails_on_item}）"

    ev = _q(
        "SELECT event_type, from_state, to_state, payload_json, assessment_question_id"
        " FROM assessment_state_event WHERE session_id=? AND event_type='DIFFICULTY_LOWERED'"
        " ORDER BY sequence_no", (sid,))[0]
    payload = json.loads(ev["payload_json"])
    for key in ("criterion", "evidence_counts", "from_difficulty", "to_difficulty"):
        assert key in payload, f"payload 缺 {key}: {payload}"
    assert payload["from_difficulty"] == "medium" and payload["to_difficulty"] == "easy", payload
    assert payload["criterion"] in ("two_consecutive_below_anchor", "followup_still_ambiguous"), payload
    assert isinstance(payload["evidence_counts"], dict), payload
    # 事件行 from/to 与 payload 一致（§13.1 迁移事件必填）
    assert ev["from_state"] == "medium" and ev["to_state"] == "easy"
    # 同事务断言：事件存在即该实例行 snapshot 已更新（current == 事件 to_state）
    rows = _q("SELECT path_state_snapshot FROM assessment_question WHERE question_id=?",
              (ev["assessment_question_id"],))
    assert rows and rows[0]["path_state_snapshot"], \
        "DIFFICULTY 事件行对应实例必须已有 snapshot（同事务）"
    snap = json.loads(rows[0]["path_state_snapshot"])
    assert snap.get("current_difficulty") == ev["to_state"], \
        f"snapshot current_difficulty 应 == 事件 to_state {ev['to_state']}，实得 {snap}"


def test_selection_reads_snapshot():
    """item 有 snapshot(current_difficulty=medium) → 该 item 后续实例 difficulty=='medium'（承接）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_diff_sel")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 答 1 题（充分证据 → easy→medium 升级 → snapshot current=medium）
    cur = _cur_q(sid, headers)
    assert cur is not None
    _answer(sid, headers, cur["question_id"], _EVIDENCE)

    raised = _q(
        "SELECT assessment_question_id FROM assessment_state_event"
        " WHERE session_id=? AND event_type='DIFFICULTY_RAISED'", (sid,))
    assert raised, "一次充分证据应触发 easy→medium（DIFFICULTY_RAISED）"
    qid = raised[0]["assessment_question_id"]
    item_rows = _q(
        "SELECT item_id, path_state_snapshot FROM assessment_question WHERE question_id=?", (qid,))
    assert item_rows and item_rows[0]["item_id"], "升级行须挂 item_id"
    item_id = item_rows[0]["item_id"]
    snap = json.loads(item_rows[0]["path_state_snapshot"])
    assert snap.get("current_difficulty") == "medium", snap

    # 选题层承接：持续作答直到该 item 再派发——该实例 difficulty 应 == medium
    # （snapshot 过滤后 easy 行出池；其余 item 正常答完不干扰）
    carried = None
    for _ in range(12):
        rows = _q(
            "SELECT difficulty FROM assessment_question"
            " WHERE session_id=? AND item_id=? AND question_id<>? AND difficulty IS NOT NULL"
            " ORDER BY seq", (sid, item_id, qid))
        if rows:
            carried = rows
            break
        cur = _cur_q(sid, headers)
        if cur is None:
            break
        row = _q("SELECT item_id FROM assessment_question WHERE question_id=?",
                 (cur["question_id"],))[0]
        if row["item_id"] == item_id:
            carried_now = _q("SELECT difficulty FROM assessment_question WHERE question_id=?",
                             (cur["question_id"],))
            # 若该实例即承接实例（question_id≠qid）：记下并断言
            if cur["question_id"] != qid:
                carried = carried_now
                break
        _answer(sid, headers, cur["question_id"], _EVIDENCE)
    assert carried, "该 item 升级后应有后续实例（snapshot 承接后）"
    assert all(row["difficulty"] == "medium" for row in carried), \
        f"升级后该 item 实例难度应为 medium，实得 {carried}"
