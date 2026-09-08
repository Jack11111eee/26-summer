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
from .facet import derive_gate_payload
from .pipeline import new_id, now_iso
from .state_events import append_event

FORM_SCHEMA_VERSION = "v2"

# status 三态（N11 代码校验，无 DB CHECK）
FORM_STATUS = ("rendered", "submitted", "superseded")

# 渲染白名单分栏（SC-1：GET /forms/{id} 只漏 form_type/title/fields；years 门槛值、
# required_level 是内部判分字段，不进快照 fields 亦不进 GET 响应）。
# v2（SSOT §16.1 facet 化）：facet（分组键）与 items（checklist 宿主 std_names）进白名单。
_FIELD_WHITELIST_KEYS = ("name", "label", "type", "required", "options", "placeholder",
                         "facet", "items")

# base 字段模板：years_of_experience 承载 experience 门槛项（_gate_check:56-63 消费）；
# qualification items 按 facet 分组展开（v2 快照——_gate_check 真值表经派生命中）
_FORM_BASE_FIELDS = [
    {"name": "years_of_experience", "label": "与岗位相关的工作年限（年）", "type": "number",
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
    """会话锚定模型的 gate=1 items（std_name/category/years/facet 两列——gate 判定与
    v2 facet 派生共用；facet_key 来自聚合落行时预打标，此处只读不重跑分类）。"""
    return [dict(r) for r in conn.execute(
        "SELECT ci.item_id, ci.std_name, ci.category, ci.years, ci.facet_key,"
        " ci.facet_params_json FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id"
        " WHERE s.session_id=? AND ci.gate=1",
        (session_id,),
    ).fetchall()]


# v2 facet 控件文案（SSOT §16.1：有序枚举单选/数字输入/勾选组；「985/211」宽读并档、
# 英语按已通过的最高等级作答——讨论稿 §2 裁决 1/开放点 1/3 措辞）
_FACET_SELECT_FIELDS = {
    "education_degree": ("education_degree", "最高学历", ["专科", "本科", "硕士", "博士"]),
    "school_tier": ("school_tier", "毕业院校档次", ["其他（非 211/985）", "211", "985"]),
    "english_level": ("english_level", "英语等级（按已通过的最高等级）", ["均未通过", "四级", "六级"]),
}
# number_range 控件 label（每 metric 一个 number field；快照 field.name = number_<metric>）
_NUMBER_METRIC_LABELS = {"age": "年龄（周岁）", "weekly_days": "每周出勤天数（天）"}


def _render_facet_fields(gate_items: list[dict]) -> list[dict]:
    """v2：gate qualification items 按 facet 分组扩展为少量收集控件（纯函数）。

    - 有序枚举（education_degree/school_tier/english_level）：每 facet 一个 select，
      宿主 std_names 进 items 键（勾选档次 → derive 按各 item facet_params 档比较）。
    - number_range：每 metric 一个 number field。
    - major_group + 长尾/存量 NULL：合并为一个 checklist（勾 = 是，不解析；
      required=False——开放点 4：不做整组必填校验，未勾 = 否）。
    """
    enum_hosts: dict[str, list[str]] = {}
    number_hosts: dict[str, list[str]] = {}
    checklist_hosts: list[str] = []
    for it in gate_items:
        if it["category"] != "qualification":
            continue  # experience 由 base 的 years_of_experience 字段承载
        key = it.get("facet_key")
        if key in _FACET_SELECT_FIELDS:
            enum_hosts.setdefault(key, []).append(it["std_name"])
        elif key == "number_range":
            params = json.loads(it["facet_params_json"] or "{}")
            metric = params.get("metric")
            if metric:
                number_hosts.setdefault(metric, []).append(it["std_name"])
        else:  # major_group / 复合断言（NULL）/ 长尾 → 勾选组
            checklist_hosts.append(it["std_name"])

    fields: list[dict] = []
    for key in ("education_degree", "school_tier", "english_level"):
        if key not in enum_hosts:
            continue
        name, label, options = _FACET_SELECT_FIELDS[key]
        fields.append({"name": name, "label": label, "type": "select",
                       "required": True, "options": options,
                       "facet": {"facet_key": key}, "items": enum_hosts[key]})
    for metric, hosts in number_hosts.items():
        label = _NUMBER_METRIC_LABELS.get(metric, f"{metric}（数值）")
        fields.append({"name": f"number_{metric}", "label": label, "type": "number",
                       "required": True, "max_len": 10,
                       "facet": {"facet_key": "number_range", "metric": metric},
                       "items": hosts})
    if checklist_hosts:
        fields.append({"name": "checked", "label": "专业与资格项（勾选符合的项）",
                       "type": "checklist", "required": False,
                       "options": checklist_hosts})
    return fields


def render_form_instance(conn, session_id: str) -> dict:
    """幂等渲染表单实例：已有 open rendered 实例直接复用，否则展开 gate items 建快照 INSERT。

    v2 快照（SSOT §16.1）：qualification items 按 facet 分组收集（枚举单选/数字/
    勾选组）；v1 已 open 实例走本函数头部复用路径原样返回（快照不可变，不迁移不重渲染）。
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

    gate_items = _gate_items(conn, session_id)
    fields = list(_FORM_BASE_FIELDS) + _render_facet_fields(gate_items)
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
    checklist（v2 勾选组）为 required=False：选项成员校验仍跑（枚举外值拒绝），
    整组必填不做（开放点 4——未勾 = 否）。
    """
    for f in fields:
        name = f["name"]
        if f.get("required") and payload.get(name) in (None, ""):
            return "FORM_MISSING_FIELD", name
        val = payload.get(name)
        if val is None:
            continue
        if f.get("options"):
            opts = f["options"]
            if f.get("type") == "checklist":
                if not isinstance(val, list) or any(v not in opts for v in val):
                    return "FORM_INVALID_OPTION", name
            elif val not in opts:
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

    v2 快照（SSOT §16.1）：payload 为 facet 答案 → 校验后 derive_gate_payload 展开为
    逐 item 真值 → payload_json 两段式落库（facet 原始答案 + derived，审计可复现）→
    derived 喂 _gate_check（经验 years_of_experience 透传数字比较）。v1 快照：payload
    原样喂 _gate_check、直接落库（存量行为零变更——快照不可变，v1 实例走旧链完投）。
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

    # v2 判据：fields 携带 facet 键或勾选组控件（v1 快照无——形态自查，不依赖 schema_version 列）
    is_v2 = any(f.get("facet") or f.get("type") == "checklist"
                for f in snapshot.get("fields", []))
    gate_items = _gate_items(conn, session_id)
    if is_v2:
        qual_items = [it for it in gate_items if it["category"] == "qualification"]
        derived = derive_gate_payload(payload, qual_items)
        # experience 的 years_of_experience 数字比较透传（_gate_check 原样消费）
        gate_payload = dict(derived)
        if payload.get("years_of_experience") is not None:
            gate_payload["years_of_experience"] = payload["years_of_experience"]
        stored_payload = {"facet_answers": payload, "derived": derived,
                          "schema_version": "v2"}
    else:
        gate_payload = payload
        stored_payload = payload

    now = now_iso()
    # status/payload 是生命周期列不是内容列（Pitfall 3 只锁 schema_snapshot/payload_json 修订面）
    conn.execute(
        "UPDATE form_instance SET status='submitted', submitted_at=?, payload_json=?"
        " WHERE form_instance_id=?",
        (now, json.dumps(stored_payload, ensure_ascii=False), form_instance_id),
    )

    gate_results: list[dict] = []
    for it in gate_items:
        passed, reason = _gate_check(it, gate_payload)
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
