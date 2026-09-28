"""Reglas del torneo, sin HTTP ni base de datos.

Todo lo que decide quién va primero vive aquí, en funciones puras, para que
se pueda probar sin levantar el servidor. Las reglas son las mismas que usa
la app del torneo en producción (`calcStandings` en torneo-volleyball-2026):

- Cada partido se juega a 3 sets FIJOS (se juegan los tres aunque uno gane
  los dos primeros). Por eso existe el 3-0.
- Un set se gana llegando a 25 con 2 de ventaja; si se pasa de 25, la
  ventaja final es exactamente 2 (26-24, 33-31).
- Puntos FIVB: victoria 3-0 = 3, victoria 2-1 = 2, derrota 1-2 = 1,
  derrota 0-3 = 0.
- Desempate, en este orden: puntos, partidos ganados, ratio de sets,
  ratio de puntos. Si aun así empatan, comparten posición.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SETS_PER_MATCH = 3
SET_TARGET = 25
MIN_LEAD = 2


class InvalidScore(ValueError):
    """El marcador no puede darse en un partido real."""


def validate_set(home: int, away: int) -> None:
    if home < 0 or away < 0:
        raise InvalidScore("los puntos no pueden ser negativos")
    if home == away:
        raise InvalidScore(f"un set no termina empatado ({home}-{away})")
    win, lose = max(home, away), min(home, away)
    if win < SET_TARGET:
        raise InvalidScore(f"{home}-{away}: el ganador debe llegar al menos a {SET_TARGET}")
    if win - lose < MIN_LEAD:
        raise InvalidScore(f"{home}-{away}: se gana con {MIN_LEAD} puntos de ventaja")
    if win > SET_TARGET and win - lose != MIN_LEAD:
        raise InvalidScore(
            f"{home}-{away}: pasado de {SET_TARGET}, el set termina en cuanto hay {MIN_LEAD} de ventaja"
        )


@dataclass(frozen=True)
class MatchResult:
    home: str
    away: str
    sets: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if self.home == self.away:
            raise InvalidScore("un equipo no puede jugar contra sí mismo")
        if len(self.sets) != SETS_PER_MATCH:
            raise InvalidScore(f"cada partido tiene {SETS_PER_MATCH} sets; llegaron {len(self.sets)}")
        for home, away in self.sets:
            validate_set(home, away)

    @property
    def sets_home(self) -> int:
        return sum(1 for h, a in self.sets if h > a)

    @property
    def sets_away(self) -> int:
        return SETS_PER_MATCH - self.sets_home

    @property
    def winner(self) -> str:
        return self.home if self.sets_home > self.sets_away else self.away


def fivb_points(sets_won: int, sets_lost: int) -> int:
    """Puntos de tabla según los sets de un partido a 3 sets fijos."""
    return {(3, 0): 3, (2, 1): 2, (1, 2): 1, (0, 3): 0}[(sets_won, sets_lost)]


def ratio(won: int, lost: int) -> float:
    """Cociente para desempatar. Sin nada perdido y algo ganado, es infinito."""
    if lost == 0:
        return 0.0 if won == 0 else math.inf
    return won / lost


@dataclass
class StandingRow:
    team: str
    played: int = 0
    won: int = 0
    lost: int = 0
    sets_won: int = 0
    sets_lost: int = 0
    points_for: int = 0
    points_against: int = 0
    points: int = 0
    position: int = 0
    tiebreak: str | None = field(default=None)

    @property
    def set_ratio(self) -> float:
        return ratio(self.sets_won, self.sets_lost)

    @property
    def point_ratio(self) -> float:
        return ratio(self.points_for, self.points_against)

    def sort_key(self) -> tuple[float, ...]:
        return (-self.points, -self.won, -self.set_ratio, -self.point_ratio)


TIEBREAK_CRITERIA = (
    ("partidos ganados", lambda r: r.won),
    ("ratio de sets", lambda r: r.set_ratio),
    ("ratio de puntos", lambda r: r.point_ratio),
)


def _explain_tie(row: StandingRow, neighbour: StandingRow) -> str:
    for name, key in TIEBREAK_CRITERIA:
        if key(row) != key(neighbour):
            return f"Empate a {row.points} pts; desempata {name}"
    return f"Empate a {row.points} pts sin desempate posible; comparten posición"


def compute_standings(teams: list[str], results: list[MatchResult]) -> list[StandingRow]:
    rows = {t: StandingRow(team=t) for t in teams}
    for m in results:
        for t in (m.home, m.away):
            if t not in rows:
                raise InvalidScore(f"el equipo '{t}' no existe en este torneo")
        home, away = rows[m.home], rows[m.away]
        sh, sa = m.sets_home, m.sets_away

        home.played += 1
        away.played += 1
        home.sets_won += sh
        home.sets_lost += sa
        away.sets_won += sa
        away.sets_lost += sh
        (home if sh > sa else away).won += 1
        (away if sh > sa else home).lost += 1
        home.points += fivb_points(sh, sa)
        away.points += fivb_points(sa, sh)
        for ph, pa in m.sets:
            home.points_for += ph
            home.points_against += pa
            away.points_for += pa
            away.points_against += ph

    # El nombre solo fija un orden estable entre empatados perfectos; no desempata.
    table = sorted(rows.values(), key=lambda r: (r.sort_key(), r.team))

    for i, row in enumerate(table):
        prev = table[i - 1] if i else None
        row.position = prev.position if prev and prev.sort_key() == row.sort_key() else i + 1
        same_points = [
            n for n in (prev, table[i + 1] if i + 1 < len(table) else None) if n and n.points == row.points
        ]
        if same_points:
            row.tiebreak = _explain_tie(row, same_points[0])
    return table
