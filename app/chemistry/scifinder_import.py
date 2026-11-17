"""Persist reviewed SciFinder extraction results in the chemistry database."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.chemistry.models import (
    ExtractionLog,
    Literature,
    Reaction,
    ReactionCondition,
    ReactionEquation,
    Scheme,
)
from app.database import chemistry_engine


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def _citation_year(source: str | None) -> int | None:
    if not source:
        return None
    match = re.search(r"\b((?:19|20)\d{2})\b", source)
    return int(match.group(1)) if match else None


def import_reviewed_reactions(
    *,
    reactions: list[dict[str, Any]],
    schemes: list[dict[str, Any]],
    file_name: str,
    source_sha256: str,
    page_count: int,
    model_used: str | None = None,
) -> dict[str, Any]:
    """Create Scheme/Reaction/Condition/Literature rows from reviewed data.

    The source fingerprint is stored with each Scheme so submitting the same PDF
    again can be detected without keeping the uploaded document on the server.
    """
    SQLModel.metadata.create_all(
        chemistry_engine,
        tables=[
            Scheme.__table__,
            Reaction.__table__,
            ReactionCondition.__table__,
            Literature.__table__,
            ExtractionLog.__table__,
            ReactionEquation.__table__,
        ],
    )

    overview_by_number = {
        int(item["scheme_number"]): item
        for item in schemes
        if item.get("scheme_number") is not None
    }
    grouped: dict[int, list[dict[str, Any]]] = {}
    for reaction in reactions:
        scheme_number = int(reaction.get("scheme_number") or 1)
        grouped.setdefault(scheme_number, []).append(reaction)

    with Session(chemistry_engine) as session:
        prior_schemes = session.exec(
            select(Scheme.scheme_number, Scheme.raw_json).where(
                Scheme.raw_json.contains(source_sha256)
            )
        ).all()
        prior_numbers = {row[0] for row in prior_schemes}
        new_grouped = {
            number: items for number, items in grouped.items()
            if number not in prior_numbers
        }
        if not new_grouped:
            return {
                "duplicate": True,
                "schemes_imported": 0,
                "reactions_imported": 0,
            }
        grouped = new_grouped

        imported_reactions = 0
        min_page = page_count or 1
        max_page = 1
        for scheme_number, items in sorted(grouped.items()):
            overview = overview_by_number.get(scheme_number, {})
            page_start = max(1, int(overview.get("page_start") or 1))
            page_end = max(page_start, int(overview.get("page_end") or page_start))
            min_page = min(min_page, page_start)
            max_page = max(max_page, page_end)
            yield_min = overview.get("yield_min")
            yield_max = overview.get("yield_max")
            overall_yield = overview.get("overall_yield")
            if not overall_yield and yield_min is not None:
                overall_yield = (
                    f"{yield_min}%" if yield_max in (None, yield_min)
                    else f"{yield_min}-{yield_max}%"
                )

            scheme = Scheme(
                scheme_number=scheme_number,
                reaction_count=int(overview.get("reaction_count") or len(items)),
                overall_yield=_as_text(overall_yield),
                overall_steps=overview.get("overall_steps", overview.get("steps")),
                description=_as_text(overview.get("description")) or f"SciFinder PDF 导入：{file_name}",
                page_start=page_start,
                page_end=page_end,
                raw_json=json.dumps(
                    {
                        "source_file": file_name,
                        "source_sha256": source_sha256,
                        "overview": overview,
                        "reactions": items,
                    },
                    ensure_ascii=False,
                ),
            )
            session.add(scheme)
            session.flush()

            for item in items:
                conditions = item.get("conditions") or {}
                if not isinstance(conditions, dict):
                    conditions = {}
                reactants = _as_text(item.get("reactants"))
                products = _as_text(item.get("products"))
                reaction = Reaction(
                    scheme_id=scheme.id,
                    cas_registry_id=(_as_text(item.get("reaction_id")) or "")[:100] or None,
                    yield_=(_as_text(item.get("yield")) or "")[:50] or None,
                    steps=overview.get("steps") or overview.get("overall_steps"),
                    reactants_text=reactants,
                    products_text=products,
                    reactants_en=reactants,
                    products_en=products,
                    page=max(1, int(item.get("page") or page_start)),
                    has_structure_image=False,
                    notes=_as_text(item.get("procedure")),
                    raw_json=json.dumps({**item, "source_file": file_name}, ensure_ascii=False),
                )
                session.add(reaction)
                session.flush()
                imported_reactions += 1

                if reactants or products:
                    session.add(ReactionEquation(
                        reaction_id=reaction.id,
                        equation_zh=f"{reactants or '未知反应物'} → {products or '未知产物'}",
                        conditions_summary="; ".join(filter(None, (
                            _as_text(conditions.get("reagents")),
                            _as_text(conditions.get("catalysts")),
                            _as_text(conditions.get("solvents")),
                            _as_text(conditions.get("temperature")),
                            _as_text(conditions.get("time")),
                        ))) or None,
                    ))

                reagents = _as_text(conditions.get("reagents"))
                catalysts = _as_text(conditions.get("catalysts"))
                solvents = _as_text(conditions.get("solvents"))
                temperature = (_as_text(conditions.get("temperature")) or "")[:200] or None
                time = (_as_text(conditions.get("time")) or "")[:200] or None
                other_parts = [
                    ("pressure", conditions.get("pressure")),
                    ("pH", conditions.get("ph")),
                    ("atmosphere", conditions.get("atmosphere")),
                    ("workup", item.get("workup")),
                    ("purification", item.get("purification")),
                    ("procedure", item.get("procedure")),
                ]
                other = "; ".join(
                    f"{label}: {_as_text(value)}"
                    for label, value in other_parts if _as_text(value)
                ) or None
                if any((reagents, catalysts, solvents, temperature, time, other)):
                    session.add(ReactionCondition(
                        reaction_id=reaction.id,
                        step_number="1",
                        reagents=reagents,
                        catalysts=catalysts,
                        solvents=solvents,
                        temperature=temperature,
                        time=time,
                        other=other,
                        raw_text=_as_text(item.get("procedure")),
                    ))

                title = _as_text(item.get("title"))
                authors = _as_text(item.get("authors"))
                source = _as_text(item.get("source"))
                doi_match = re.search(r"10\.\d{4,9}/[^\s\]}>]+", source or "", re.I)
                doi = doi_match.group(0).rstrip(".,;") if doi_match else None
                if title or authors or source:
                    session.add(Literature(
                        reaction_id=reaction.id,
                        title=title,
                        authors=authors,
                        journal=source[:500] if source else None,
                        year=_citation_year(source),
                        doi=doi[:255] if doi else None,
                        raw_text=source,
                    ))

        batch_number = session.exec(
            select(func.max(ExtractionLog.batch_number))
        ).one() or 0
        session.add(ExtractionLog(
            batch_number=int(batch_number) + 1,
            page_start=min_page,
            page_end=max_page,
            status="success",
            schemes_found=len(grouped),
            reactions_found=imported_reactions,
            raw_response=json.dumps(
                {"source_file": file_name, "source_sha256": source_sha256},
                ensure_ascii=False,
            ),
            model_used=model_used,
            duration_seconds=0.0,
            created_at=datetime.utcnow(),
        ))
        session.commit()

    return {
        "duplicate": False,
        "schemes_imported": len(grouped),
        "reactions_imported": imported_reactions,
    }
