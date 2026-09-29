"""Contratos de entrada y salida. Lo que aquí se declara es lo que publica el OpenAPI."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import SETS_PER_MATCH, InvalidScore, MatchResult

TeamId = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,60}$", examples=["aguilas-carmesi"])]
MatchStatus = Literal["pending", "in_progress", "completed"]


class Schema(BaseModel):
    # strict: el contrato dice boolean y entero; "0" o 0 no cuelan como false.
    model_config = ConfigDict(extra="forbid", strict=True)


class Team(Schema):
    id: TeamId
    name: str = Field(examples=["Águilas Carmesí"])
    seed: int = Field(description="Orden de siembra con que empezó la temporada (1 = cabeza).")


class TeamRef(Schema):
    id: TeamId
    name: str = Field(examples=["Águilas Carmesí"])


class Jornada(Schema):
    number: int = Field(ge=1, examples=[3])
    name: str = Field(examples=["Jornada 3"])
    date: str | None = Field(description="Fecha ISO 8601 (AAAA-MM-DD).", examples=["2026-07-11"])
    city: str | None = Field(examples=["San Carlos"])
    status: MatchStatus = Field(description="Se deriva de sus partidos.")


class SetScore(Schema):
    home: int = Field(ge=0, le=99, examples=[25])
    away: int = Field(ge=0, le=99, examples=[22])


class Result(Schema):
    sets_home: int = Field(ge=0, le=SETS_PER_MATCH)
    sets_away: int = Field(ge=0, le=SETS_PER_MATCH)
    winner: TeamRef


class Match(Schema):
    id: str = Field(examples=["j3-p2"], description="`j{jornada}-p{posición}`")
    jornada: int
    position: int = Field(description="Orden dentro de la jornada.")
    home: TeamRef
    away: TeamRef
    status: MatchStatus
    sets: list[SetScore]
    result: Result | None = Field(description="Solo en partidos terminados.")


class MatchPage(Schema):
    data: list[Match]
    total: int = Field(description="Partidos que cumplen el filtro, sin paginar.")
    limit: int
    offset: int


class Ratio(Schema):
    won: int
    lost: int
    ratio: float | None = Field(
        description="won / lost con 3 decimales. `null` si no perdió nada y ganó algo (infinito)."
    )


class StandingRow(Schema):
    position: int = Field(description="Dos equipos empatados en todo comparten posición.")
    team: TeamRef
    played: int
    won: int
    lost: int
    points: int = Field(description="Puntos FIVB: 3-0 = 3, 2-1 = 2, 1-2 = 1, 0-3 = 0.")
    sets: Ratio
    rally_points: Ratio = Field(description="Puntos anotados y recibidos en los sets.")
    tiebreak: str | None = Field(
        description="Por qué va delante o detrás de un equipo con los mismos puntos.",
        examples=["Empate a 11 pts; desempata ratio de sets"],
    )


class Standings(Schema):
    through_jornada: int | None = Field(description="Última jornada contada; `null` si ninguna.")
    matches_counted: int
    rows: list[StandingRow]


class FinalMatch(Schema):
    id: str = Field(examples=["ff-p4"], description="`ff-p{posición}`")
    round: Literal["semifinal_1", "semifinal_2", "third_place", "final"]
    round_name: str = Field(examples=["Final"])
    home: TeamRef
    away: TeamRef
    winner: TeamRef


class Podium(Schema):
    champion: TeamRef
    runner_up: TeamRef
    third: TeamRef
    fourth: TeamRef


class FinalPhase(Schema):
    date: str = Field(examples=["2026-09-26"])
    city: str = Field(examples=["Churube"])
    score_recorded: bool = Field(
        description="`false`: la fase final se jugó sin anotar los puntos; de cada partido solo se sabe "
        "quién ganó. Por eso no hay sets ni marcador."
    )
    matches: list[FinalMatch]
    podium: Podium = Field(description="Sale de la final y del partido por el 3.er puesto, no de la tabla.")


class SimResult(Schema):
    home: TeamId
    away: TeamId
    sets: list[SetScore] = Field(min_length=SETS_PER_MATCH, max_length=SETS_PER_MATCH)

    @model_validator(mode="after")
    def _real_score(self) -> SimResult:
        try:
            self.to_domain()
        except InvalidScore as exc:
            raise ValueError(str(exc)) from exc
        return self

    def to_domain(self) -> MatchResult:
        return MatchResult(self.home, self.away, tuple((s.home, s.away) for s in self.sets))


class Simulation(Schema):
    results: list[SimResult] = Field(max_length=200)
    include_season: bool = Field(
        default=True,
        description="Si es `true`, los resultados se suman a los reales de la temporada.",
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "include_season": True,
                    "results": [
                        {
                            "home": "shalom-2",
                            "away": "aguilas-carmesi",
                            "sets": [
                                {"home": 25, "away": 20},
                                {"home": 26, "away": 24},
                                {"home": 25, "away": 18},
                            ],
                        }
                    ],
                }
            ]
        },
    )


class Health(Schema):
    status: Literal["ok"]
    version: str
    matches_loaded: int


class Problem(Schema):
    """Error en formato RFC 9457 (application/problem+json)."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(examples=["https://api.davidameth.dev/problems/not-found"])
    title: str = Field(examples=["Recurso no encontrado"])
    status: int = Field(examples=[404])
    detail: str | None = Field(default=None, examples=["No existe el equipo 'aguilas'."])
    instance: str | None = Field(default=None, examples=["/v1/teams/aguilas"])


def as_ratio(won: int, lost: int, value: float) -> Ratio:
    return Ratio(won=won, lost=lost, ratio=None if math.isinf(value) else round(value, 3))
