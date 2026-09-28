"""La carga de la temporada se niega a arrancar con datos imposibles."""

import copy

import pytest

from app.data import SEED, load_season, parse
from app.domain import InvalidScore

BASE = {
    "tournament": {"id": "t"},
    "teams": [{"id": "a", "name": "A", "seed": 1}, {"id": "b", "name": "B", "seed": 2}],
    "jornadas": [{"number": 1, "name": "Jornada 1", "date": None, "city": None}],
    "matches": [
        {
            "id": "j1-p1",
            "jornada": 1,
            "position": 1,
            "home": "a",
            "away": "b",
            "status": "completed",
            "sets": [[25, 20], [25, 20], [25, 20]],
        },
    ],
}


def con(**cambios):
    raw = copy.deepcopy(BASE)
    raw["matches"][0].update(cambios)
    return raw


def test_el_archivo_real_carga():
    season = load_season()
    assert SEED.name == "temporada-2026.json"
    assert len(season.matches) == 21


def test_jornada_inexistente():
    with pytest.raises(ValueError, match="jornada 9"):
        parse(con(jornada=9))


def test_equipo_inexistente():
    with pytest.raises(ValueError, match="equipo desconocido"):
        parse(con(away="z"))


def test_marcador_imposible_no_arranca():
    with pytest.raises(InvalidScore):
        parse(con(sets=[[25, 24], [25, 20], [25, 20]]))


@pytest.mark.parametrize(
    "estados,esperado",
    [(["pending"], "pending"), (["completed", "pending"], "in_progress"), (["completed"], "completed")],
)
def test_estado_de_jornada_derivado(estados, esperado):
    raw = copy.deepcopy(BASE)
    raw["matches"] = [
        {
            **BASE["matches"][0],
            "id": f"j1-p{i}",
            "position": i,
            "status": s,
            "sets": BASE["matches"][0]["sets"] if s == "completed" else [],
        }
        for i, s in enumerate(estados, 1)
    ]
    season = parse(raw)
    assert season.jornada_status(1) == esperado
    pendiente = next((m for m in season.matches if m.status == "pending"), None)
    assert pendiente is None or pendiente.result is None
