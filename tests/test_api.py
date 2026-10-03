"""La API por HTTP: rutas, filtros, errores y cabeceras."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VICTORIA_LIMPIA = [{"home": 25, "away": 20}] * 3


def es_problema(r, status, slug):
    assert r.status_code == status
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["status"] == status
    assert body["type"].endswith(f"/problems/{slug}")
    assert body["instance"] == r.request.url.path
    assert body["request_id"] == r.headers["x-request-id"]
    return body


# ------------------------------------------------------------------ lectura


def test_equipos_en_orden_de_siembra():
    teams = client.get("/v1/teams").json()
    assert len(teams) == 7
    assert [t["seed"] for t in teams] == list(range(1, 8))


def test_un_equipo():
    assert client.get("/v1/teams/shalom-2").json() == {"id": "shalom-2", "name": "Shalom 2", "seed": 7}


def test_jornadas_con_estado_derivado():
    jornadas = client.get("/v1/jornadas").json()
    assert [j["number"] for j in jornadas] == list(range(1, 8))
    assert {j["status"] for j in jornadas} == {"completed"}
    assert client.get("/v1/jornadas/3").json()["city"] == "San Carlos"


def test_partido_con_resultado_coherente():
    m = client.get("/v1/matches/j1-p3").json()
    assert m["home"]["id"] == "little-giant"
    assert len(m["sets"]) == 3
    ganados = sum(1 for s in m["sets"] if s["home"] > s["away"])
    assert (m["result"]["sets_home"], m["result"]["sets_away"]) == (ganados, 3 - ganados)


def test_la_liga_tiene_21_partidos_y_cada_equipo_juega_6():
    assert client.get("/v1/matches?limit=50").json()["total"] == 21
    for team in client.get("/v1/teams").json():
        assert client.get(f"/v1/matches?team={team['id']}").json()["total"] == 6


def test_filtros_combinados():
    page = client.get("/v1/matches?jornada=2&status=completed").json()
    assert page["total"] > 0
    assert all(m["jornada"] == 2 for m in page["data"])


def test_paginacion_recorre_todo_sin_repetir():
    ids, offset = [], 0
    while True:
        page = client.get(f"/v1/matches?limit=4&offset={offset}").json()
        ids += [m["id"] for m in page["data"]]
        if not page["data"]:
            break
        offset += 4
    assert len(ids) == len(set(ids)) == 21


def test_filtro_sin_resultados_es_lista_vacia_no_404():
    r = client.get("/v1/matches?team=no-existe")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.headers["x-total-count"] == "0"


def test_tabla_historica():
    tras_j1 = client.get("/v1/standings?through_jornada=1").json()
    assert tras_j1["through_jornada"] == 1
    assert tras_j1["matches_counted"] == 3
    assert sum(r["played"] for r in tras_j1["rows"]) == 6


def test_tabla_explica_los_empates():
    rows = client.get("/v1/standings").json()["rows"]
    segundo = rows[1]
    assert segundo["points"] == rows[2]["points"]
    assert "desempata" in segundo["tiebreak"]


# ------------------------------------------------------------------ simulación


def test_simular_suma_a_la_temporada_sin_guardar():
    antes = client.get("/v1/standings").json()
    r = client.post(
        "/v1/standings/simulate",
        json={"results": [{"home": "shalom-1", "away": "generacion-de-fe", "sets": VICTORIA_LIMPIA}]},
    )
    assert r.status_code == 200
    shalom = next(row for row in r.json()["rows"] if row["team"]["id"] == "shalom-1")
    assert (shalom["points"], shalom["played"]) == (7, 7)
    assert client.get("/v1/standings").json() == antes


def test_simular_desde_cero():
    r = client.post(
        "/v1/standings/simulate",
        json={
            "include_season": False,
            "results": [{"home": "roca-eterna", "away": "shalom-2", "sets": VICTORIA_LIMPIA}],
        },
    ).json()
    assert r["matches_counted"] == 1
    assert r["rows"][0]["team"]["id"] == "roca-eterna"
    assert r["rows"][0]["sets"]["ratio"] is None  # 3-0: ratio infinito se publica como null


@pytest.mark.parametrize(
    "resultado,campo",
    [
        ({"home": "shalom-1", "away": "shalom-2", "sets": [{"home": 25, "away": 24}] * 3}, "results.0"),
        ({"home": "shalom-1", "away": "shalom-2", "sets": VICTORIA_LIMPIA[:2]}, "results.0.sets"),
        ({"home": "shalom-1", "away": "shalom-1", "sets": VICTORIA_LIMPIA}, "results.0"),
        ({"home": "SHALOM", "away": "shalom-2", "sets": VICTORIA_LIMPIA}, "results.0.home"),
        ({"home": "shalom-1", "away": "shalom-2", "sets": VICTORIA_LIMPIA, "extra": 1}, "results.0.extra"),
    ],
)
def test_simular_rechaza_lo_imposible(resultado, campo):
    body = es_problema(
        client.post("/v1/standings/simulate", json={"results": [resultado]}), 422, "validation"
    )
    assert any(e["field"] == f"body.{campo}" for e in body["errors"]), body["errors"]


def test_simular_con_equipo_que_no_existe():
    r = client.post(
        "/v1/standings/simulate",
        json={"results": [{"home": "real-madrid", "away": "shalom-2", "sets": VICTORIA_LIMPIA}]},
    )
    assert "real-madrid" in es_problema(r, 422, "invalid-score")["detail"]


# ------------------------------------------------------------------ errores


@pytest.mark.parametrize(
    "ruta",
    [
        "/v1/teams/aguilas",
        "/v1/jornadas/99",
        "/v1/matches/j9-p9",
        "/v1/standings?through_jornada=40",
        "/v1/nada",
    ],
)
def test_404_en_formato_rfc_9457(ruta):
    es_problema(client.get(ruta), 404, "not-found")


def test_parametro_fuera_de_rango():
    body = es_problema(client.get("/v1/matches?limit=500"), 422, "validation")
    assert body["errors"][0]["field"] == "query.limit"


def test_metodo_no_permitido_dice_cuales_si():
    r = client.delete("/v1/teams")
    es_problema(r, 405, "method-not-allowed")
    assert r.headers["allow"] == "GET"


def test_head_como_get_sin_cuerpo():
    get = client.get("/v1/standings")
    head = client.head("/v1/standings")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["etag"] == get.headers["etag"]
    assert head.headers["content-length"] == get.headers["content-length"]
    assert client.head("/v1/teams/nope").status_code == 404


def test_cuerpo_que_no_es_json():
    r = client.post(
        "/v1/standings/simulate", content=b"{no es json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code in (400, 422)
    assert r.headers["content-type"] == "application/problem+json"


def test_cada_tipo_de_error_esta_documentado():
    for slug in ["not-found", "validation", "invalid-score", "bad-request", "method-not-allowed", "internal"]:
        assert client.get(f"/problems/{slug}").json()["type"] == slug


def test_error_inesperado_no_filtra_detalles():
    @app.get("/_explota", include_in_schema=False)
    def _explota():
        raise RuntimeError("secreto interno")

    try:
        r = TestClient(app, raise_server_exceptions=False).get("/_explota")
        body = es_problema(r, 500, "internal")
        assert "secreto" not in r.text
        assert body["detail"] is None
    finally:
        app.router.routes.pop()


# ------------------------------------------------------------------ HTTP


def test_etag_y_304():
    r = client.get("/v1/standings")
    etag = r.headers["etag"]
    # `private`: un CDN no puede guardarla (ver test_ninguna_respuesta_con_id_es_publica).
    assert r.headers["cache-control"] == "private, max-age=300"
    again = client.get("/v1/standings", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert client.get("/v1/standings", headers={"If-None-Match": '"otro"'}).status_code == 200


def test_el_etag_cambia_con_la_consulta():
    a = client.get("/v1/standings?through_jornada=1").headers["etag"]
    b = client.get("/v1/standings?through_jornada=2").headers["etag"]
    assert a != b


def test_request_id_propio_o_generado():
    assert (
        client.get("/health", headers={"X-Request-ID": "prueba-123"}).headers["x-request-id"] == "prueba-123"
    )
    generado = client.get("/health").headers["x-request-id"]
    assert len(generado) == 32
    # Uno absurdamente largo no se refleja: se genera otro.
    assert client.get("/health", headers={"X-Request-ID": "x" * 500}).headers["x-request-id"] != "x" * 500


# Antes esta prueba solo miraba /health, la única ruta que no se cachea, y por
# eso no vio el defecto de producción del 2026-10-02: con `public`, el CDN de
# Vercel servía el mismo X-Request-ID a todos durante cinco minutos.
GET_CACHEABLES = ["/v1/teams", "/v1/jornadas", "/v1/matches", "/v1/standings", "/v1/final-phase"]


@pytest.mark.parametrize("ruta", GET_CACHEABLES)
def test_las_rutas_cacheables_tambien_respetan_el_request_id(ruta):
    r = client.get(ruta, headers={"X-Request-ID": "propio-456"})
    assert r.headers["x-request-id"] == "propio-456"


@pytest.mark.parametrize("ruta", GET_CACHEABLES)
def test_ninguna_respuesta_con_id_es_publica(ruta):
    # Una respuesta que lleva un X-Request-ID por petición no puede guardarla
    # una caché compartida: la repetiría a otros clientes.
    cache = client.get(ruta).headers["cache-control"]
    assert "private" in cache
    assert "public" not in cache and "s-maxage" not in cache


def test_cors_abierto_para_leer():
    r = client.get("/v1/teams", headers={"Origin": "https://ejemplo.com"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_salud_y_raiz():
    assert client.get("/health").json() == {"status": "ok", "version": "1.0.0", "matches_loaded": 21}
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/docs"


# ------------------------------------------------------------------ fase final


def test_fase_final_sin_marcador_y_con_podio():
    ff = client.get("/v1/final-phase").json()
    assert (ff["date"], ff["city"], ff["score_recorded"]) == ("2026-09-26", "Churube", False)
    assert [m["round"] for m in ff["matches"]] == ["semifinal_1", "semifinal_2", "third_place", "final"]
    final = ff["matches"][3]
    assert ff["podium"]["champion"] == final["winner"]
    assert "sets" not in final  # se jugó sin anotar: no se inventa un marcador


def test_la_fase_final_no_toca_la_tabla_de_la_liga():
    tabla = client.get("/v1/standings").json()
    assert tabla["matches_counted"] == 21
    assert sum(r["played"] for r in tabla["rows"]) == 42
    semifinalistas = {
        t["id"] for m in client.get("/v1/final-phase").json()["matches"][:2] for t in (m["home"], m["away"])
    }
    assert semifinalistas == {r["team"]["id"] for r in tabla["rows"][:4]}
