"""API pública del Torneo Volleyball 2026."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import domain, schemas
from app.data import Season, load_season

VERSION = "1.0.0"

PROBLEMS = {
    "not-found": ("Recurso no encontrado", "El identificador no corresponde a nada en esta temporada."),
    "validation": ("Petición no válida", "Algún campo no cumple el contrato; `errors` dice cuál y por qué."),
    "invalid-score": ("Marcador imposible", "El resultado no puede darse con las reglas del torneo."),
    "bad-request": (
        "Petición mal formada",
        "El servidor no pudo leer la petición; por ejemplo, un cuerpo que no es JSON.",
    ),
    "method-not-allowed": ("Método no permitido", "La ruta existe pero no acepta ese método."),
    "internal": ("Error interno", "Algo falló de nuestro lado. El `request_id` sirve para rastrearlo."),
}

DESCRIPTION = """
Datos reales de la liga del **Torneo Volleyball 2026** (7 equipos, 21 partidos,
63 sets), servidos como API REST de solo lectura, más un endpoint que recalcula
la tabla con resultados hipotéticos.

- La tabla se calcula en cada petición a partir de los parciales de cada set;
  no hay posiciones guardadas que puedan desincronizarse.
- Los errores siguen el formato **RFC 9457** (`application/problem+json`).
- Las respuestas llevan `ETag`: repetir la petición con `If-None-Match`
  devuelve `304` sin cuerpo.
- Cada respuesta lleva `X-Request-ID` (o reutiliza el que envíes).

Los datos se exportaron de la base de producción sin jugadores ni ningún otro
dato personal.
"""

app = FastAPI(
    docs_url=None,
    title="API del Torneo Volleyball 2026",
    version=VERSION,
    description=DESCRIPTION,
    contact={"name": "David Ameth Martínez Sánchez", "url": "https://davidameth.dev"},
    license_info={"name": "MIT", "identifier": "MIT"},
    openapi_tags=[
        {"name": "equipos", "description": "Los 7 equipos de la liga."},
        {"name": "jornadas", "description": "Fechas de juego y su estado."},
        {"name": "partidos", "description": "Resultados set a set, con filtros y paginación."},
        {"name": "tabla", "description": "Clasificación FIVB con desempates explicados."},
        {"name": "sistema", "description": "Salud del servicio y catálogo de errores."},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Request-ID", "X-Total-Count"],
)


# ---------------------------------------------------------------- errores


def problem(
    request: Request,
    status: int,
    slug: str,
    detail: str | None,
    headers: dict[str, str] | None = None,
    **extra,
) -> JSONResponse:
    title, _ = PROBLEMS[slug]
    # Un 500 lo atiende ServerErrorMiddleware, por fuera del middleware que pone
    # X-Request-ID; por eso la cabecera se pone también aquí.
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    headers = {**(headers or {}), "X-Request-ID": rid}
    body = {
        "type": f"{request.base_url}problems/{slug}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": rid,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


class NotFound(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


@app.exception_handler(NotFound)
async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
    return problem(request, 404, "not-found", exc.detail)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 405:
        # RFC 9110 obliga a decir qué métodos sí se aceptan; Starlette lo trae en exc.headers.
        return problem(
            request,
            405,
            "method-not-allowed",
            f"{request.method} no se admite aquí.",
            headers=exc.headers,
        )
    if exc.status_code == 404:
        return problem(request, 404, "not-found", f"No existe la ruta {request.url.path}.")
    # Cualquier otro (p. ej. un cuerpo que no es JSON) conserva su código; antes
    # se convertía en 404 y las pruebas de contrato lo cazaron.
    return problem(request, exc.status_code, "bad-request", str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(p) for p in e["loc"]),
            "message": e["msg"].removeprefix("Value error, "),
        }
        for e in exc.errors()
    ]
    return problem(request, 422, "validation", f"{len(errors)} campo(s) no válido(s).", errors=errors)


@app.exception_handler(domain.InvalidScore)
async def _invalid_score(request: Request, exc: domain.InvalidScore) -> JSONResponse:
    return problem(request, 422, "invalid-score", str(exc))


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    return problem(request, 500, "internal", None)


# ---------------------------------------------------------------- cabeceras


class HeadAsGet:
    """RFC 9110: todo lo que acepta GET acepta HEAD, con las mismas cabeceras y sin cuerpo.

    FastAPI no lo hace solo (respondía 405). Se atiende como GET y se descarta
    el cuerpo al enviarlo, así Content-Length y ETag son los del GET.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.app(scope, receive, send)

        async def send_without_body(message):
            if message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, send_without_body)


app.add_middleware(HeadAsGet)


@app.middleware("http")
async def request_id(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def cached(request: Request, payload) -> Response:
    """JSON con ETag fuerte. Los datos son una foto fija: el ETag no caduca solo."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=300"}
    matches = [t.strip() for t in request.headers.get("if-none-match", "").split(",")]
    if etag in matches or "*" in matches:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


# ---------------------------------------------------------------- conversores


def team_ref(season: Season, team_id: str) -> schemas.TeamRef:
    t = season.team(team_id)
    assert t is not None
    return schemas.TeamRef(id=t.id, name=t.name)


def match_out(season: Season, m) -> schemas.Match:
    result = None
    if m.result:
        result = schemas.Result(
            sets_home=m.result.sets_home,
            sets_away=m.result.sets_away,
            winner=team_ref(season, m.result.winner),
        )
    sets = m.result.sets if m.result else ()
    return schemas.Match(
        id=m.id,
        jornada=m.jornada,
        position=m.position,
        home=team_ref(season, m.home),
        away=team_ref(season, m.away),
        status=m.status,
        sets=[schemas.SetScore(home=h, away=a) for h, a in sets],
        result=result,
    )


def standings_out(season: Season, rows: list[domain.StandingRow]) -> list[schemas.StandingRow]:
    return [
        schemas.StandingRow(
            position=r.position,
            team=team_ref(season, r.team),
            played=r.played,
            won=r.won,
            lost=r.lost,
            points=r.points,
            sets=schemas.as_ratio(r.sets_won, r.sets_lost, r.set_ratio),
            rally_points=schemas.as_ratio(r.points_for, r.points_against, r.point_ratio),
            tiebreak=r.tiebreak,
        )
        for r in rows
    ]


def dump(model) -> object:
    return model.model_dump(mode="json")


# ---------------------------------------------------------------- rutas

NOT_FOUND = {404: {"model": schemas.Problem, "description": "No existe."}}
INVALID = {
    400: {"model": schemas.Problem, "description": "La petición no se pudo leer."},
    422: {"model": schemas.Problem, "description": "La petición no cumple el contrato."},
}
CACHED = {304: {"description": "Sin cambios desde el `ETag` enviado en `If-None-Match`."}}

v1 = APIRouter(prefix="/v1", responses={500: {"model": schemas.Problem}})


@v1.get(
    "/teams", summary="Listar equipos", tags=["equipos"], response_model=list[schemas.Team], responses=CACHED
)
def list_teams(request: Request):
    """Los equipos, en orden de siembra."""
    season = load_season()
    return cached(request, [dump(schemas.Team(id=t.id, name=t.name, seed=t.seed)) for t in season.teams])


@v1.get(
    "/teams/{team_id}",
    summary="Un equipo",
    tags=["equipos"],
    response_model=schemas.Team,
    responses={**NOT_FOUND, **CACHED},
)
def get_team(request: Request, team_id: schemas.TeamId):
    t = load_season().team(team_id)
    if t is None:
        raise NotFound(f"No existe el equipo '{team_id}'.")
    return cached(request, dump(schemas.Team(id=t.id, name=t.name, seed=t.seed)))


@v1.get(
    "/jornadas",
    summary="Listar jornadas",
    tags=["jornadas"],
    response_model=list[schemas.Jornada],
    responses=CACHED,
)
def list_jornadas(request: Request):
    season = load_season()
    return cached(request, [dump(jornada_out(season, j.number)) for j in season.jornadas])


@v1.get(
    "/jornadas/{number}",
    summary="Una jornada",
    tags=["jornadas"],
    response_model=schemas.Jornada,
    responses={**NOT_FOUND, **CACHED},
)
def get_jornada(request: Request, number: int):
    season = load_season()
    if season.jornada(number) is None:
        raise NotFound(f"No existe la jornada {number}.")
    return cached(request, dump(jornada_out(season, number)))


def jornada_out(season: Season, number: int) -> schemas.Jornada:
    j = season.jornada(number)
    assert j is not None
    return schemas.Jornada(
        number=j.number, name=j.name, date=j.date, city=j.city, status=season.jornada_status(number)
    )


@v1.get(
    "/matches",
    summary="Buscar partidos",
    tags=["partidos"],
    response_model=schemas.MatchPage,
    responses={**INVALID, **CACHED},
)
def list_matches(
    request: Request,
    jornada: Annotated[int | None, Query(ge=1, description="Solo esa jornada.")] = None,
    team: Annotated[schemas.TeamId | None, Query(description="Partidos donde juega ese equipo.")] = None,
    status: Annotated[schemas.MatchStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Partidos en orden de jornada y posición.

    Un filtro por un equipo o una jornada que no existen devuelve una lista
    vacía, no un 404: es una búsqueda sin resultados.
    """
    found = [
        m
        for m in load_season().matches
        if (jornada is None or m.jornada == jornada)
        and (team is None or team in (m.home, m.away))
        and (status is None or m.status == status)
    ]
    season = load_season()
    page = schemas.MatchPage(
        data=[match_out(season, m) for m in found[offset : offset + limit]],
        total=len(found),
        limit=limit,
        offset=offset,
    )
    response = cached(request, dump(page))
    response.headers["X-Total-Count"] = str(len(found))
    return response


@v1.get(
    "/matches/{match_id}",
    summary="Un partido",
    tags=["partidos"],
    response_model=schemas.Match,
    responses={**NOT_FOUND, **CACHED},
)
def get_match(request: Request, match_id: str):
    season = load_season()
    m = season.match(match_id)
    if m is None:
        raise NotFound(f"No existe el partido '{match_id}'.")
    return cached(request, dump(match_out(season, m)))


@v1.get(
    "/standings",
    summary="Tabla de posiciones",
    tags=["tabla"],
    response_model=schemas.Standings,
    responses={**NOT_FOUND, **INVALID, **CACHED},
)
def get_standings(
    request: Request,
    through_jornada: Annotated[
        int | None,
        Query(ge=1, description="Tabla tal como quedó al cerrar esa jornada. Sin él, la actual."),
    ] = None,
):
    """Clasificación calculada en el momento a partir de los parciales de cada set."""
    season = load_season()
    if through_jornada is not None and season.jornada(through_jornada) is None:
        raise NotFound(f"No existe la jornada {through_jornada}.")
    counted = [
        m for m in season.matches if m.result and (through_jornada is None or m.jornada <= through_jornada)
    ]
    rows = domain.compute_standings([t.id for t in season.teams], [m.result for m in counted])
    last = through_jornada or max((m.jornada for m in counted), default=None)
    out = schemas.Standings(
        through_jornada=last, matches_counted=len(counted), rows=standings_out(season, rows)
    )
    return cached(request, dump(out))


@v1.post(
    "/standings/simulate",
    summary="Simular la tabla",
    tags=["tabla"],
    response_model=schemas.Standings,
    responses=INVALID,
)
def simulate_standings(body: schemas.Simulation):
    """Recalcula la tabla con resultados hipotéticos. No guarda nada.

    Cada resultado pasa por las mismas reglas que los reales: 3 sets, sets a 25
    con 2 de ventaja. Un marcador imposible devuelve `422 invalid-score`.
    """
    season = load_season()
    real = [m.result for m in season.matches if m.result] if body.include_season else []
    extra = [r.to_domain() for r in body.results]
    rows = domain.compute_standings([t.id for t in season.teams], real + extra)
    return schemas.Standings(
        through_jornada=None, matches_counted=len(real) + len(extra), rows=standings_out(season, rows)
    )


app.include_router(v1)


def openapi_with_problems() -> dict:
    """Todos los errores salen como application/problem+json, y así se documentan.

    FastAPI declara por defecto los 4xx como application/json con su propio
    esquema de validación; las pruebas de contrato detectaron que el documento
    no decía la verdad. Aquí se corrige una vez para todas las rutas.
    """
    if app.openapi_schema:
        return app.openapi_schema
    spec = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        contact=app.contact,
        license_info=app.license_info,
    )
    problem_ref = {"$ref": "#/components/schemas/Problem"}
    spec["components"]["schemas"]["Problem"] = schemas.Problem.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    for path in spec["paths"].values():
        for op in path.values():
            for code, response in op.get("responses", {}).items():
                if code[0] in "45":
                    response["content"] = {"application/problem+json": {"schema": problem_ref}}
                    if code == "422":
                        response["description"] = "La petición no cumple el contrato."
    for unused in ("HTTPValidationError", "ValidationError"):
        spec["components"]["schemas"].pop(unused, None)
    app.openapi_schema = spec
    return spec


app.openapi = openapi_with_problems


@app.get("/health", summary="Salud del servicio", tags=["sistema"], response_model=schemas.Health)
def health():
    return schemas.Health(status="ok", version=VERSION, matches_loaded=len(load_season().matches))


@app.get("/problems/{slug}", summary="Describir un tipo de error", tags=["sistema"], responses=NOT_FOUND)
def describe_problem(request: Request, slug: str) -> dict[str, str]:
    """Documenta cada `type` de error que puede devolver la API."""
    if slug not in PROBLEMS:
        raise NotFound(f"No hay un tipo de error llamado '{slug}'.")
    title, text = PROBLEMS[slug]
    return {"type": slug, "title": title, "description": text}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/swagger", include_in_schema=False)
def swagger():
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} · Swagger")


SCALAR = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>API del Torneo Volleyball 2026</title>
</head>
<body>
  <script id="api-reference" data-url="/openapi.json"></script>
  <script>
    document.getElementById("api-reference").dataset.configuration = JSON.stringify({
      theme: "default",
      servers: [{ url: window.location.origin, description: "Este servidor" }],
      hideClientButton: false,
      defaultHttpClient: { targetKey: "shell", clientKey: "curl" },
      metaData: { title: "API del Torneo Volleyball 2026" },
    });
  </script>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference@1"></script>
</body>
</html>"""


@app.get("/docs", include_in_schema=False)
def docs():
    """Referencia con Scalar: lee el mismo /openapi.json y trae su propio cliente de pruebas."""
    return HTMLResponse(SCALAR)
