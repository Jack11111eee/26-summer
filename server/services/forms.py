"""表单链服务（SSOT §16.1——03-01 form_instance 不可变快照 + 六维校验 + gate 结构化判定）。

form_instance 是不可变 schema 快照：status 生命周期（rendered/submitted/superseded）、
revision 不可变（修订 = INSERT 新行 revision+1，同 form_instance_id；旧行仅 UPDATE
status='superseded'——Pitfall 3 只锁 schema_snapshot/payload_json 修订面）。

- render_form_instance：幂等（已有 open rendered 实例不重复 INSERT），快照 = base
  模板 + 会话模型 gate=1 的 qualification items 动态展开（experience 由 base 的
  years_of_experience 字段承载——_gate_check 消费口径）。
- validate_and_submit：六维序（①所有权在 API 层 load_owned_session；②status 409
  FORM_ALREADY_SUBMITTED；③revision 409 FORM_INSTANCE_REVISION_CONFLICT；④必填
  422 FORM_MISSING_FIELD / ⑤枚举 422 FORM_INVALID_OPTION / ⑥长度 422
  FORM_FIELD_TOO_LONG），成功写 gate 行（question_id/score_state NULL 结构化结果）。

事务边界（D-06）：render_form_instance / validate_and_submit / revise_instance 接 conn
但不 commit——实例写入与状态事件在调用者同一事务内完成（difficulty.py 同契约）。
"""
import json

from .aggregation import _gate_check
from .pipeline import new_id, now_iso
from .state_events import append_event

FORM_SCHEMA_VERSION = "v1"

# status 三态（N11 代码校验，无 DB CHECK）
FORM_STATUS = ("rendered", "submitted", "superseded")

# 渲染白名单分栏（SC-1：GET /forms/{id} 只漏 form_type/title/fields；years 门槛值、
# required_level 是内部判分字段，不进快照 fields 亦不进 GET 响应）
_FIELD_WHITELIST_KEYS = ("name", "label", "type", "required", "options", "placeholder")

# base 字段模板：years_of_experience 承载 experience 门槛项（_gate_check:56-63 消费）；
# qualification items 动态展开（select 二值——_gate_check:66-69 消费 '是' 真值表）
_FORM_BASE_FIELDS = [
    {"name": "years_of_experience", "label": "工作年限（年）", "type": "number",
     "required": True, "max_len": 10},
]


def whitelist_form(snapshot: dict) -> dict:
    """渲染白名单 dict：form_type/title + fields 逐项滤白名单键（max_len 等内部列剥离）。"""
    return {
        "form_type": snapshot.get("form_type"),
        "title": snapshot.get("title"),
        "fields": [
            {k: f[k] for k in _FIELD_WHITELIST_KEYS if k in f}
            for f in snapshot.get("fields", [])
        ],
    }


def _gate_items(conn, session_id: str) -> list[dict]:
    """会话锚定模型的 gate=1 items（std_name/category/years——gate 判定与快照展开共用）。"""
    return [dict(r) for r in conn.execute(
        "SELECT ci.item_id, ci.std_name, ci.category, ci.years FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id"
        " WHERE s.session_id=? AND ci.gate=1",
        (session_id,),
    ).fetchall()]


def render_form_instance(conn, session_id: str) -> dict:
    """幂等渲染表单实例：已有 open rendered 实例直接复用，否则展开 gate items 建快照 INSERT。

    返回渲染白名单 dict（form_instance_id + form_type/title/fields）。接 conn 不 commit。
    """
    row = conn.execute(
        "SELECT form_instance_id, schema_snapshot FROM form_instance"
        " WHERE session_id=? AND status='rendered' ORDER BY revision DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is not None:
        snapshot = json.loads(row["schema_snapshot"])
        return {"form_instance_id": row["form_instance_id"], **whitelist_form(snapshot)}

    fields = list(_FORM_BASE_FIELDS)
    for it in _gate_items(conn, session_id):
        if it["category"] == "qualification":
            # qualification items 动态展开：select 二值（'是' 在 _gate_check 真值表）
            fields.append({"name": it["std_name"], "label": it["std_name"], "type": "select",
                           "required": True, "options": ["是", "否"]})
        # experience item 由 base 的 years_of_experience 字段承载，不再单独展开字段
    snapshot = {"form_type": "gate_combined", "title": "资格核验", "fields": fields}
    fi_id = new_id("fi")
    conn.execute(
        "INSERT INTO form_instance(form_instance_id, session_id, form_type, schema_version,"
        " schema_snapshot, status, revision, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (fi_id, session_id, snapshot["form_type"], FORM_SCHEMA_VERSION,
         json.dumps(snapshot, ensure_ascii=False), "rendered", 1, now_iso()),
    )
    append_event(conn, session_id=session_id, event_type="FORM_RENDERED",
                 actor_type="system",
                 payload={"form_instance_id": fi_id, "form_type": snapshot["form_type"],
                          "schema_version": FORM_SCHEMA_VERSION})
    return {"form_instance_id": fi_id, **whitelist_form(snapshot)}


def _all_gate_items_collected(conn, session_id: str) -> bool:
    """会话模型 gate items 是否全采集（存在 submitted 实例即全采集——快照含全部 gate 字段）。

    无 gate item 模型恒 True（m5/p0_security gate=0 种子面不动）。表单链闭合判据：
    池耗尽时据此判定走 render（未采集）还是 finish（已采集）。
    """
    if _gate_items(conn, session_id) == []:
        return True
    submitted = conn.execute(
        "SELECT 1 FROM form_instance WHERE session_id=? AND status='submitted' LIMIT 1",
        (session_id,),
    ).fetchone()
    return submitted is not None


def _validate_payload(fields: list[dict], payload: dict) -> tuple[str | None, str | None]:
    """六维的后三维纯函数：④必填 / ⑤枚举 / ⑥长度。返回 (error_code, field_name) 或 (None, None)。

    逐项校验（schema_snapshot 的 fields 顺序），三项序 = 必填 → 枚举 → 长度。
    """
    for f in fields:
        name = f["name"]
        if f.get("required") and payload.get(name) in (None, ""):
            return "FORM_MISSING_FIELD", name
        val = payload.get(name)
        if val is None:
            continue
        if f.get("options") and val not in f["options"]:
            return "FORM_INVALID_OPTION", name
        if f.get("max_len") and len(str(val)) > f["max_len"]:
            return "FORM_FIELD_TOO_LONG", name
    return None, None


def validate_and_submit(conn, *, session_id: str, form_instance_id: str, payload: dict,
                        expected_revision: int, user: dict) -> dict:
    """六维校验 + gate 行写入（成功路径）。返回 dict（ok 标志 + status/gate_results 或 error）。

    ②status 非 rendered → 409 FORM_ALREADY_SUBMITTED（首次结果 payload_json 原样带回）；
    ③expected_revision 不匹配 → 409 FORM_INSTANCE_REVISION_CONFLICT；
    ④⑤⑥ → 422 三态 error_code（API 层翻译为 HTTPException）。接 conn 不 commit。
    """
    row = conn.execute(
        "SELECT form_instance_id, status, revision, schema_snapshot, payload_json"
        " FROM form_instance WHERE form_instance_id=? AND session_id=?",
        (form_instance_id, session_id),
    ).fetchone()
    if row is None:
        return {"ok": False, "error_code": "FORM_NOT_FOUND", "field": None, "payload": None}
    if row["status"] != "rendered":
        first_payload = json.loads(row["payload_json"]) if row["payload_json"] else None
        return {"ok": False, "error_code": "FORM_ALREADY_SUBMITTED",
                "field": None, "payload": first_payload}
    if row["revision"] != expected_revision:
        return {"ok": False, "error_code": "FORM_INSTANCE_REVISION_CONFLICT",
                "field": None, "payload": None}
    snapshot = json.loads(row["schema_snapshot"])
    err_code, field_name = _validate_payload(snapshot.get("fields", []), payload)
    if err_code is not None:
        return {"ok": False, "error_code": err_code, "field": field_name, "payload": None}

    now = now_iso()
    # status/payload 是生命周期列不是内容列（Pitfall 3 只锁 schema_snapshot/payload_json 修订面）
    conn.execute(
        "UPDATE form_instance SET status='submitted', submitted_at=?, payload_json=?"
        " WHERE form_instance_id=?",
        (now, json.dumps(payload, ensure_ascii=False), form_instance_id),
    )

    gate_results: list[dict] = []
    for it in _gate_items(conn, session_id):
        passed, reason = _gate_check(it, payload)
        result = "true" if passed else "false"
        # gate 行：结构化结果（question_id/score_state NULL——§16.1 复用评分表）
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
            " score_live, score_final, evidence_quote, reason, created_at, score_state,"
            " gate_result, gate_status, gate_reason, evaluated_schema_version, evaluated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qs"), session_id, None, it["item_id"], None, None, None, None,
             now, None, result, "EVALUATED", reason, FORM_SCHEMA_VERSION, now),
        )
        gate_results.append({"item_id": it["item_id"], "std_name": it["std_name"],
                             "gate_result": result, "gate_reason": reason})
        append_event(conn, session_id=session_id, event_type="GATE_EVALUATED",
                     actor_type="system",
                     payload={"item_id": it["item_id"], "gate_result": result,
                              "gate_reason": reason})
    append_event(conn, session_id=session_id, event_type="FORM_SUBMITTED",
                 actor_type="candidate", actor_id=user["user_id"],
                 payload={"form_instance_id": form_instance_id,
                          "schema_version": FORM_SCHEMA_VERSION})
    return {"ok": True, "status": "submitted", "gate_results": gate_results}


def revise_instance(conn, *, form_instance_id: str) -> dict:
    """修订（admin 再触发 render）：INSERT 新行 revision=旧+1（同 form_instance_id）+ 旧行
    UPDATE status='superseded'（仅 status 生命周期列；schema_snapshot 不可变不 UPDATE）。
    """
    row = conn.execute(
        "SELECT session_id, form_type, schema_version, schema_snapshot, revision"
        " FROM form_instance WHERE form_instance_id=? ORDER BY revision DESC LIMIT 1",
        (form_instance_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"表单实例不存在: {form_instance_id}")
    new_revision = row["revision"] + 1
    conn.execute(
        "UPDATE form_instance SET status='superseded' WHERE form_instance_id=? AND revision=?",
        (form_instance_id, row["revision"]),
    )
    conn.execute(
        "INSERT INTO form_instance(form_instance_id, session_id, form_type, schema_version,"
        " schema_snapshot, status, revision, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (form_instance_id, row["session_id"], row["form_type"], row["schema_version"],
         row["schema_snapshot"], "rendered", new_revision, now_iso()),
    )
    return {"form_instance_id": form_instance_id, "revision": new_revision}
