"""JD 导入与单 JD 详情（P2）。导入即返回，解析交后台任务；前端轮询状态。"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status

from ... import schemas
from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import new_id, now_iso, run_parse_pipeline

router = APIRouter(prefix="/api/admin", tags=["admin-jds"], dependencies=[Depends(require_admin)])


@router.get("/positions")
def list_positions() -> list[dict]:
    """岗位列表（M1 简版：id/名称/状态/JD 数）。完整 P1 岗位库在 M3 实现。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.position_id, p.name, p.status,"
        " (SELECT COUNT(*) FROM jd_record j WHERE j.position_id=p.position_id) AS jd_count"
        " FROM position p ORDER BY p.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _insert_jd(jd_text: str, company: str | None, source_type: str) -> str:
    jd_id = new_id("jd")
    conn = get_conn()
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (jd_id, None, None, company, source_type, jd_text, "imported", now_iso()),
    )
    conn.commit()
    return jd_id


@router.post("/jds/import")
def import_jd(body: schemas.JdImportRequest, background: BackgroundTasks) -> dict:
    """粘贴导入，不要求选岗位（归岗全自动）。"""
    jd_id = _insert_jd(body.jd_text, body.company, "paste")
    background.add_task(run_parse_pipeline, jd_id)
    return {"jd_id": jd_id, "status": "imported"}


@router.post("/jds/import-file")
async def import_file(background: BackgroundTasks, file: UploadFile) -> dict:
    """JSONL 批量上传：每行 {"id"?,"position"?,"company","jd_text"}。"""
    raw = (await file.read()).decode("utf-8")
    jd_ids = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"第 {lineno} 行不是合法 JSON")
        jd_text = obj.get("jd_text")
        if not jd_text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"第 {lineno} 行缺少 jd_text")
        jd_ids.append(_insert_jd(jd_text, obj.get("company"), "file"))
    for jd_id in jd_ids:
        background.add_task(run_parse_pipeline, jd_id)
    return {"imported": len(jd_ids), "jd_ids": jd_ids}


@router.get("/positions/{position_id}/jds")
def list_jds(position_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, job_title, company, source_type, status, low_confidence,"
        " error_msg, created_at FROM jd_record WHERE position_id=? ORDER BY created_at DESC",
        (position_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/jds/{jd_id}")
def jd_detail(jd_id: str) -> dict:
    """单 JD 工序留档：原文/清洗/raw_items/std_items/错误信息。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM jd_record WHERE jd_id=?", (jd_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "JD 不存在")
    d = dict(row)
    for k in ("raw_items_json", "std_items_json"):
        if d.get(k):
            d[k.replace("_json", "")] = json.loads(d[k])
    return d


@router.post("/jds/{jd_id}/reparse")
def reparse(jd_id: str, background: BackgroundTasks) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT status FROM jd_record WHERE jd_id=?", (jd_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "JD 不存在")
    conn.execute("UPDATE jd_record SET status='imported', error_msg=NULL WHERE jd_id=?", (jd_id,))
    conn.commit()
    background.add_task(run_parse_pipeline, jd_id)
    return {"jd_id": jd_id, "status": "reimported"}
