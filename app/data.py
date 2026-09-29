"""Carga la temporada desde data/temporada-2026.json.

Es una foto fija de la base de producción (ver scripts/export_seed.py), así
que se lee una sola vez. Cada partido pasa por las mismas reglas que valida
la API: si el archivo trae un marcador imposible, el servidor no arranca.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from app.domain import KnockoutMatch, MatchResult, Podium, compute_standings, podium

SEED = Path(__file__).resolve().parent.parent / "data" / "temporada-2026.json"


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    seed: int


@dataclass(frozen=True)
class Jornada:
    number: int
    name: str
    date: str | None
    city: str | None


@dataclass(frozen=True)
class Match:
    id: str
    jornada: int
    position: int
    home: str
    away: str
    status: str
    result: MatchResult | None


@dataclass(frozen=True)
class FinalMatch:
    id: str
    position: int
    round_name: str
    match: KnockoutMatch


@dataclass(frozen=True)
class FinalPhase:
    date: str
    city: str
    score_recorded: bool
    matches: tuple[FinalMatch, ...]
    podium: Podium


@dataclass(frozen=True)
class Season:
    tournament: dict
    teams: tuple[Team, ...]
    jornadas: tuple[Jornada, ...]
    matches: tuple[Match, ...]
    final_phase: FinalPhase | None = None

    def team(self, team_id: str) -> Team | None:
        return next((t for t in self.teams if t.id == team_id), None)

    def jornada(self, number: int) -> Jornada | None:
        return next((j for j in self.jornadas if j.number == number), None)

    def match(self, match_id: str) -> Match | None:
        return next((m for m in self.matches if m.id == match_id), None)

    def jornada_status(self, number: int) -> str:
        """Se deriva de sus partidos; la app del torneo tampoco lo guarda."""
        states = {m.status for m in self.matches if m.jornada == number}
        if not states or states == {"pending"}:
            return "pending"
        return "completed" if states == {"completed"} else "in_progress"


def parse(raw: dict) -> Season:
    teams = tuple(Team(**t) for t in raw["teams"])
    known = {t.id for t in teams}
    jornadas = tuple(Jornada(**j) for j in raw["jornadas"])
    numbers = {j.number for j in jornadas}
    matches = []
    for m in raw["matches"]:
        if m["jornada"] not in numbers:
            raise ValueError(f"{m['id']}: la jornada {m['jornada']} no existe")
        if {m["home"], m["away"]} - known:
            raise ValueError(f"{m['id']}: equipo desconocido")
        # Solo un partido cerrado tiene resultado: en uno pendiente o en curso
        # los parciales están incompletos y no se pueden validar como finales.
        result = None
        if m["status"] == "completed":
            result = MatchResult(m["home"], m["away"], tuple(tuple(s) for s in m["sets"]))
        matches.append(Match(m["id"], m["jornada"], m["position"], m["home"], m["away"], m["status"], result))
    season = Season(raw["tournament"], teams, jornadas, tuple(matches))
    if "final_phase" in raw:
        season = replace(season, final_phase=parse_final(raw["final_phase"], season))
    return season


def parse_final(raw: dict, season: Season) -> FinalPhase:
    """La fase final se valida contra la liga: sus semifinalistas son los cuatro primeros."""
    table = compute_standings([t.id for t in season.teams], [m.result for m in season.matches if m.result])
    top4 = [r.team for r in table[:4]]
    matches = tuple(
        FinalMatch(
            m["id"],
            m["position"],
            m["round_name"],
            KnockoutMatch(m["round"], m["home"], m["away"], m["winner"]),
        )
        for m in raw["matches"]
    )
    return FinalPhase(
        date=raw["date"],
        city=raw["city"],
        score_recorded=raw["score_recorded"],
        matches=matches,
        podium=podium(top4, [f.match for f in matches]),
    )


@cache
def load_season() -> Season:
    return parse(json.loads(SEED.read_text(encoding="utf-8")))
