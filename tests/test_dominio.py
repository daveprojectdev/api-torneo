"""Reglas del voleibol y de la tabla, sin HTTP."""

import math
import random
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain import (
    InvalidScore,
    KnockoutMatch,
    MatchResult,
    Podium,
    compute_standings,
    fivb_points,
    podium,
    ratio,
    validate_set,
)

TEAMS = ["a", "b", "c", "d", "e"]


# ------------------------------------------------------------------ sets


@pytest.mark.parametrize("home,away", [(25, 0), (25, 23), (23, 25), (26, 24), (33, 31), (3, 25)])
def test_set_valido(home, away):
    validate_set(home, away)


@pytest.mark.parametrize(
    "home,away,motivo",
    [
        (25, 24, "ventaja"),  # sin los 2 de ventaja
        (24, 22, "al menos a 25"),  # nadie llegó a 25
        (27, 24, "en cuanto hay"),  # pasado de 25 debió acabar en 26-24
        (30, 20, "en cuanto hay"),
        (25, 25, "empatado"),
        (-1, 25, "negativos"),
    ],
)
def test_set_imposible(home, away, motivo):
    with pytest.raises(InvalidScore, match=motivo):
        validate_set(home, away)


# ------------------------------------------------------------------ partidos


def test_partido_necesita_tres_sets():
    with pytest.raises(InvalidScore, match="3 sets"):
        MatchResult("a", "b", ((25, 20), (25, 20)))


def test_un_equipo_no_juega_contra_si_mismo():
    with pytest.raises(InvalidScore, match="sí mismo"):
        MatchResult("a", "a", ((25, 20), (25, 20), (25, 20)))


def test_ganador_y_sets():
    m = MatchResult("a", "b", ((19, 25), (25, 12), (25, 17)))
    assert (m.sets_home, m.sets_away, m.winner) == (2, 1, "a")


@pytest.mark.parametrize("won,lost,pts", [(3, 0, 3), (2, 1, 2), (1, 2, 1), (0, 3, 0)])
def test_puntos_fivb(won, lost, pts):
    assert fivb_points(won, lost) == pts


def test_ratio_sin_derrotas_es_infinito():
    assert ratio(6, 0) == math.inf
    assert ratio(0, 0) == 0.0
    assert ratio(3, 2) == 1.5


# ------------------------------------------------------------------ desempates


def partido(home, away, *sets):
    return MatchResult(home, away, tuple(sets))


W = (25, 20)  # set ganado por el local
L = (20, 25)  # set ganado por el visitante


def test_desempata_partidos_ganados():
    # Mismos puntos con distinto número de victorias:
    # a: gana 3-0 (3) y pierde 0-3 (0)          = 3 pts, 1 ganado
    # c: pierde 1-2 tres veces (1 + 1 + 1)      = 3 pts, 0 ganados
    results = [
        partido("a", "d", W, W, W),
        partido("e", "a", W, W, W),
        partido("c", "d", W, L, L),
        partido("c", "e", W, L, L),
        partido("c", "b", W, L, L),
    ]
    table = {r.team: r for r in compute_standings(TEAMS, results)}
    assert table["a"].points == table["c"].points == 3
    assert table["a"].position < table["c"].position
    assert table["a"].tiebreak == "Empate a 3 pts; desempata partidos ganados"


def test_desempata_ratio_de_puntos_y_si_no_comparten_posicion():
    results = [partido("a", "b", (25, 10), W, W), partido("c", "d", W, W, W)]
    table = compute_standings(TEAMS, results)
    assert [r.team for r in table[:2]] == ["a", "c"]
    assert table[0].tiebreak == "Empate a 3 pts; desempata ratio de puntos"

    # Dos equipos idénticos en todo: misma posición y lo dice.
    twins = compute_standings(TEAMS, [partido("a", "b", W, W, W), partido("c", "d", W, W, W)])
    assert twins[0].position == twins[1].position == 1
    assert "comparten posición" in twins[0].tiebreak
    assert twins[2].position == 3


def test_equipo_desconocido():
    with pytest.raises(InvalidScore, match="no existe"):
        compute_standings(TEAMS, [partido("a", "zzz", W, W, W)])


# ------------------------------------------------------------------ propiedades


@st.composite
def set_valido(draw):
    lose = draw(st.integers(0, 40))
    win = 25 if lose <= 23 else lose + 2
    return (win, lose) if draw(st.booleans()) else (lose, win)


@st.composite
def temporada(draw):
    n = draw(st.integers(0, 30))
    results = []
    for _ in range(n):
        home, away = draw(st.permutations(TEAMS))[:2]
        sets = tuple(draw(set_valido()) for _ in range(3))
        results.append(MatchResult(home, away, sets))
    return results


@settings(max_examples=300)
@given(set_valido())
def test_todo_set_generado_es_valido(s):
    validate_set(*s)


@settings(max_examples=300)
@given(temporada())
def test_invariantes_de_la_tabla(results):
    table = compute_standings(TEAMS, results)
    n = len(results)

    assert sorted(r.team for r in table) == sorted(TEAMS)
    assert sum(r.played for r in table) == 2 * n
    assert sum(r.won for r in table) == sum(r.lost for r in table) == n
    assert sum(r.sets_won for r in table) == sum(r.sets_lost for r in table) == 3 * n
    assert sum(r.points_for for r in table) == sum(r.points_against for r in table)
    # Cada partido reparte 3 puntos, sea 3-0 (3+0) o 2-1 (2+1).
    assert sum(r.points for r in table) == 3 * n
    for r in table:
        assert r.won + r.lost == r.played
        assert r.sets_won + r.sets_lost == 3 * r.played

    # Ordenada, posiciones que empiezan en 1 y nunca retroceden.
    assert [r.sort_key() for r in table] == sorted(r.sort_key() for r in table)
    assert table[0].position == 1
    assert all(a.position <= b.position for a, b in pairwise(table))


@settings(max_examples=150)
@given(temporada(), st.randoms(use_true_random=False))
def test_el_orden_de_los_partidos_no_cambia_la_tabla(results, rnd: random.Random):
    shuffled = results[:]
    rnd.shuffle(shuffled)
    first = [(r.team, r.points, r.position) for r in compute_standings(TEAMS, results)]
    second = [(r.team, r.points, r.position) for r in compute_standings(TEAMS, shuffled)]
    assert first == second


# ------------------------------------------------------------------ fase final

TOP4 = ["a", "b", "c", "d"]


def cuadro(**cambios):
    base = {
        "semifinal_1": KnockoutMatch("semifinal_1", "a", "d", "a"),
        "semifinal_2": KnockoutMatch("semifinal_2", "b", "c", "c"),
        "third_place": KnockoutMatch("third_place", "d", "b", "b"),
        "final": KnockoutMatch("final", "a", "c", "c"),
    }
    base.update(cambios)
    return list(base.values())


def test_podio_de_un_cuadro_valido():
    assert podium(TOP4, cuadro()) == Podium(champion="c", runner_up="a", third="b", fourth="d")


@pytest.mark.parametrize(
    "cambio,motivo",
    [
        ({"semifinal_1": KnockoutMatch("semifinal_1", "a", "e", "a")}, "cuatro primeros"),
        ({"semifinal_2": KnockoutMatch("semifinal_2", "a", "c", "c")}, "las dos semifinales"),
        ({"third_place": KnockoutMatch("third_place", "a", "b", "b")}, "perdedores de semifinal"),
        ({"final": KnockoutMatch("final", "a", "d", "a")}, "ganadores de semifinal"),
    ],
)
def test_cuadro_imposible(cambio, motivo):
    with pytest.raises(InvalidScore, match=motivo):
        podium(TOP4, cuadro(**cambio))


def test_falta_un_partido_de_la_fase_final():
    with pytest.raises(InvalidScore, match="exactamente"):
        podium(TOP4, cuadro()[:3])


def test_el_ganador_tiene_que_haber_jugado():
    with pytest.raises(InvalidScore, match="no jugó"):
        KnockoutMatch("final", "a", "b", "c")
    with pytest.raises(InvalidScore, match="sí mismo"):
        KnockoutMatch("final", "a", "a", "a")
    with pytest.raises(InvalidScore, match="ronda desconocida"):
        KnockoutMatch("cuartos", "a", "b", "a")
