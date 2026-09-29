"""La tabla de la API tiene que ser idéntica a la que publica la app del torneo.

Copiada a mano de https://torneo-volleyball-2026.vercel.app (pestaña Tabla) el
2026-09-27, con la liga cerrada. Son dos implementaciones independientes
(TypeScript en la app, Python aquí) sobre los mismos datos: si discrepan en un
solo número, una de las dos está mal.
"""

from fastapi.testclient import TestClient

from app.main import app

# posición, equipo, jugados, ganados, sets, puntos anotados-recibidos, PTS
PRODUCCION = [
    (1, "Generación de Fe", 6, 5, (12, 6), (417, 339), 12),
    (2, "Little Giant", 6, 4, (11, 7), (412, 348), 11),
    (3, "Centinelas de Luz", 6, 3, (11, 7), (410, 351), 11),
    (4, "Águilas Carmesí", 6, 4, (9, 9), (403, 401), 9),
    (5, "Roca Eterna", 6, 2, (9, 9), (362, 398), 9),
    (6, "Shalom 2", 6, 2, (7, 11), (362, 429), 7),
    (7, "Shalom 1", 6, 1, (4, 14), (344, 444), 4),
]


def test_la_tabla_coincide_con_la_app_en_produccion():
    rows = TestClient(app).get("/v1/standings").json()["rows"]
    obtenida = [
        (
            r["position"],
            r["team"]["name"],
            r["played"],
            r["won"],
            (r["sets"]["won"], r["sets"]["lost"]),
            (r["rally_points"]["won"], r["rally_points"]["lost"]),
            r["points"],
        )
        for r in rows
    ]
    assert obtenida == PRODUCCION


# Podio de la portada de la app (archivada), copiado el 2026-09-28.
PODIO_PRODUCCION = {
    "champion": "Centinelas de Luz",
    "runner_up": "Little Giant",
    "third": "Águilas Carmesí",
    "fourth": "Generación de Fe",
}


def test_el_podio_coincide_con_la_app_en_produccion():
    podium = TestClient(app).get("/v1/final-phase").json()["podium"]
    assert {k: v["name"] for k, v in podium.items()} == PODIO_PRODUCCION
