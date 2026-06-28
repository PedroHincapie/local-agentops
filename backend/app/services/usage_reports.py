"""Reportes de uso: ``/api/usage/today`` (§4.5) y ``/api/usage/history`` (§4.6).

Costo y tokens son **acumulados por sesión** en el statusline, así que los totales
de un periodo suman el **máximo por sesión** (nunca todos los ticks). Los *peaks* de
las ventanas son el ``max`` sobre los snapshots statusline. ccusage no participa en
estas agregaciones (otra base contable); es respaldo histórico.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import date, datetime
from typing import Any

from sqlmodel import Session, func, select

from app.models import AgentSession, Project, UsageSnapshot, Workday
from app.services.usage import cost_today_usd


def _today_local() -> str:
    return datetime.now().date().isoformat()


def _sum_optional(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present), 6) if present else None


def _peaks(
    db: Session, workday_ids: list[str], session_ids: list[str] | None = None
) -> tuple[float | None, float | None]:
    """max(5h%), max(7d%) sobre los snapshots statusline. None si no hay datos."""
    if session_ids is not None and not session_ids:
        return (None, None)
    stmt = (
        select(
            func.max(UsageSnapshot.rate_limit_5h_percentage),
            func.max(UsageSnapshot.rate_limit_7d_percentage),
        )
        .where(UsageSnapshot.workday_id.in_(workday_ids))  # type: ignore[attr-defined]
        .where(UsageSnapshot.source_name == "statusline")
    )
    if session_ids is not None:
        stmt = stmt.where(UsageSnapshot.session_id.in_(session_ids))  # type: ignore[union-attr]
    row = db.exec(stmt).one()
    return row[0], row[1]


def _session_rollups(
    db: Session,
    workday_id: str,
    *,
    project: str | None = None,
    model: str | None = None,
    task_type: str | None = None,
) -> list[dict[str, Any]]:
    """Rollup por sesión (máximos acumulados) de una jornada, con filtros opcionales."""
    sessions = list(
        db.exec(select(AgentSession).where(AgentSession.workday_id == workday_id)).all()
    )
    if not sessions:
        return []
    proj_ids = {s.project_id for s in sessions if s.project_id}
    projects = {
        p.id: p
        for p in (
            db.exec(select(Project).where(Project.id.in_(proj_ids))).all()  # type: ignore[attr-defined]
            if proj_ids
            else []
        )
    }

    rollups: list[dict[str, Any]] = []
    for s in sessions:
        project_name = projects[s.project_id].name if s.project_id in projects else None
        if project is not None and project_name != project:
            continue
        if model is not None and s.model != model:
            continue
        if task_type is not None and s.task_type != task_type:
            continue
        cost, in_tok, out_tok = db.exec(
            select(
                func.max(UsageSnapshot.cost_session_usd),
                func.max(UsageSnapshot.total_input_tokens),
                func.max(UsageSnapshot.total_output_tokens),
            )
            .where(UsageSnapshot.session_id == s.id)
            .where(UsageSnapshot.source_name == "statusline")
        ).one()
        rollups.append(
            {
                "session_id": s.id,
                "project_name": project_name,
                "model": s.model,
                "task_type": s.task_type,
                "cost_usd": cost,
                "in_tokens": in_tok or 0,
                "out_tokens": out_tok or 0,
            }
        )
    return rollups


def _statusline_snapshot_count(db: Session, workday_id: str) -> int:
    return db.exec(
        select(func.count())
        .select_from(UsageSnapshot)
        .where(UsageSnapshot.workday_id == workday_id)
        .where(UsageSnapshot.source_name == "statusline")
    ).one()


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_snapshot_at(db: Session) -> str | None:
    last = db.exec(
        select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()
    return _isoformat(last.captured_at) if last else None


def build_usage_today(db: Session) -> dict[str, Any]:
    workday = db.exec(select(Workday).where(Workday.date == _today_local())).first()
    if workday is None:
        return {
            "workday_id": None,
            "status": "critical",
            "cost_today_usd": None,
            "peak_five_hour_percentage": None,
            "peak_seven_day_percentage": None,
            "totals": {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "snapshots": 0,
                "sessions": 0,
            },
            "by_project": [],
            "by_task_type": [],
            "last_snapshot_at": _last_snapshot_at(db),
        }

    rollups = _session_rollups(db, workday.id)
    peak5, peak7 = _peaks(db, [workday.id])

    by_project_acc: dict[str | None, dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0, "sessions": 0}
    )
    by_task_acc: dict[str | None, float] = defaultdict(float)
    for r in rollups:
        g = by_project_acc[r["project_name"]]
        g["cost"] += r["cost_usd"] or 0.0
        g["sessions"] += 1
        by_task_acc[r["task_type"]] += r["cost_usd"] or 0.0

    return {
        "workday_id": workday.id,
        "status": workday.current_state or "critical",
        "cost_today_usd": cost_today_usd(db, workday.id),
        "peak_five_hour_percentage": peak5,
        "peak_seven_day_percentage": peak7,
        "totals": {
            "total_input_tokens": sum(r["in_tokens"] for r in rollups),
            "total_output_tokens": sum(r["out_tokens"] for r in rollups),
            "snapshots": _statusline_snapshot_count(db, workday.id),
            "sessions": len(rollups),
        },
        "by_project": [
            {
                "project_name": name,
                "cost_usd": round(v["cost"], 6),
                "sessions": int(v["sessions"]),
            }
            for name, v in by_project_acc.items()
        ],
        "by_task_type": [
            {"task_type": tt, "cost_usd": round(cost, 6)} for tt, cost in by_task_acc.items()
        ],
        "last_snapshot_at": _last_snapshot_at(db),
    }


def _bucket_key(day: str, granularity: str) -> str:
    if granularity == "month":
        return day[:7]  # YYYY-MM
    if granularity == "week":
        y, w, _ = date.fromisoformat(day).isocalendar()
        return f"{y}-W{w:02d}"
    return day  # day


def build_usage_history(
    db: Session,
    granularity: str = "day",
    date_from: str | None = None,
    date_to: str | None = None,
    project: str | None = None,
    model: str | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    if granularity not in ("day", "week", "month"):
        granularity = "day"
    filtered = any(x is not None for x in (project, model, task_type))

    workdays = list(
        db.exec(select(Workday).order_by(Workday.date)).all()  # type: ignore[attr-defined]
    )
    workdays = [
        w
        for w in workdays
        if (date_from is None or w.date >= date_from)
        and (date_to is None or w.date <= date_to)
    ]

    buckets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for w in workdays:
        rollups = _session_rollups(
            db, w.id, project=project, model=model, task_type=task_type
        )
        if filtered and not rollups:
            continue
        session_ids = [r["session_id"] for r in rollups] if filtered else None
        peak5, peak7 = _peaks(db, [w.id], session_ids)
        cost = _sum_optional([r["cost_usd"] for r in rollups])

        key = _bucket_key(w.date, granularity)
        b = buckets.setdefault(
            key,
            {
                "period": key,
                "cost_usd": None,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "peak_five_hour_percentage": None,
                "peak_seven_day_percentage": None,
                "sessions": 0,
            },
        )
        if cost is not None:
            b["cost_usd"] = round((b["cost_usd"] or 0.0) + cost, 6)
        b["total_input_tokens"] += sum(r["in_tokens"] for r in rollups)
        b["total_output_tokens"] += sum(r["out_tokens"] for r in rollups)
        b["peak_five_hour_percentage"] = _max_opt(b["peak_five_hour_percentage"], peak5)
        b["peak_seven_day_percentage"] = _max_opt(b["peak_seven_day_percentage"], peak7)
        b["sessions"] += len(rollups)

    return {"granularity": granularity, "series": list(buckets.values())}


def _max_opt(a: float | None, b: float | None) -> float | None:
    present = [v for v in (a, b) if v is not None]
    return max(present) if present else None
