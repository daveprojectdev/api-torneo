# API del Torneo Volleyball 2026

API REST pública con los datos reales del [Torneo Volleyball 2026](https://torneo.davidameth.dev):
la liga (7 equipos, 21 partidos y 63 sets) y la fase final con su podio. Calcula la tabla de posiciones con
puntos FIVB y explica cada desempate. También tiene un endpoint para simular resultados hipotéticos.

Hecha con **Python 3.14 + FastAPI + Pydantic**. **100 pruebas** y **99 % de cobertura**.

## Probarla

| | |
|---|---|
| Documentación interactiva | [api.davidameth.dev/docs](https://api.davidameth.dev/docs), para llamar a cada ruta desde el navegador |
| Swagger UI | [/swagger](https://api.davidameth.dev/swagger) |
| Referencia | [/redoc](https://api.davidameth.dev/redoc) |
| Contrato OpenAPI 3.1 | [/openapi.json](https://api.davidameth.dev/openapi.json) |

```bash
curl https://api.davidameth.dev/v1/standings
curl "https://api.davidameth.dev/v1/matches?team=shalom-2&limit=3"
curl -X POST https://api.davidameth.dev/v1/standings/simulate \
  -H "Content-Type: application/json" \
  -d '{"results":[{"home":"shalom-1","away":"generacion-de-fe","sets":[{"home":25,"away":20},{"home":26,"away":24},{"home":25,"away":18}]}]}'
```

## Rutas

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/v1/teams` · `/v1/teams/{id}` | Equipos, en orden de siembra |
| GET | `/v1/jornadas` · `/v1/jornadas/{n}` | Fechas de juego; el estado se deriva de sus partidos |
| GET | `/v1/matches` | Partidos set a set. Filtros `jornada`, `team`, `status`; paginación `limit`/`offset` |
| GET | `/v1/matches/{id}` | Un partido (`j3-p2` = jornada 3, posición 2) |
| GET | `/v1/standings?through_jornada=n` | La tabla actual, o como quedó al cerrar la jornada `n` |
| POST | `/v1/standings/simulate` | Recalcula la tabla con resultados hipotéticos. No guarda nada |
| GET | `/v1/final-phase` | Semifinales, 3.er puesto, final y el podio que sale de ellos |
| GET | `/health` · `/problems/{tipo}` | Salud del servicio y catálogo de errores |

## Decisiones de diseño

- **La tabla no se guarda, se calcula.** Sale de los parciales de cada set en cada petición, así que no hay
  posiciones almacenadas que puedan desincronizarse. La app del torneo aprendió eso en producción: el conteo de
  sets guardado vino mal una vez, y desde entonces se deriva de los parciales. Esta API hace lo mismo.
- **Las reglas viven aparte del HTTP.** `app/domain.py` son funciones puras (sets a 25 con 2 de ventaja,
  3 sets fijos, puntos FIVB 3-2-1-0, desempate por partidos ganados, ratio de sets y ratio de puntos).
  Se prueban sin levantar el servidor.
- **Un marcador imposible no entra por ningún lado.** Las mismas reglas validan el archivo de datos al
  arrancar (con un 25-24 el servidor no arranca) y cada resultado simulado (devuelve `422`).
- **Errores en formato RFC 9457** (`application/problem+json`), con `type`, `title`, `status`, `detail`,
  `instance` y `request_id`. Cada `type` se documenta en `/problems/{tipo}`.
- **Validación estricta.** Los campos que no existen se rechazan (`extra="forbid"`) y no hay conversiones
  silenciosas: `0` no se acepta como `false` ni `"25"` como número.
- **Caché HTTP.** Cada GET lleva `ETag` y `Cache-Control: private`; con `If-None-Match` la respuesta es `304` sin
  cuerpo. `private` y no `public`: la respuesta lleva un `X-Request-ID` por petición, y una caché compartida
  (el CDN) la repetiría a otros clientes.
- **Trazabilidad.** Todas las respuestas, también los 500, llevan `X-Request-ID`. Si el cliente manda uno, se
  reutiliza. Un error inesperado no expone detalles internos.
- **Versionada** bajo `/v1`.
- **Una búsqueda sin resultados es `200` con lista vacía**, no `404`. El `404` es para recursos concretos
  que no existen.

## Cómo está probada

```
tests/
├── test_dominio.py            reglas del voleibol + propiedades con Hypothesis
├── test_api.py                rutas, filtros, paginación, errores y cabeceras HTTP
├── test_contrato.py           Schemathesis genera peticiones desde el OpenAPI
├── test_datos.py              la carga se niega a arrancar con datos imposibles
└── test_oraculo_produccion.py la tabla y el podio coinciden con los de la app en producción
```

- **Oráculo de producción.** La app del torneo (TypeScript) y esta API (Python) calculan la tabla por separado
  con los mismos datos. La prueba exige que coincidan en cada número de cada fila, y que el podio sea el mismo.
- **Pruebas de propiedades.** Hypothesis genera cientos de temporadas al azar y comprueba invariantes que tienen
  que cumplirse siempre. Cada partido reparte exactamente 3 puntos, los sets ganados suman lo mismo que los
  perdidos, la tabla sale ordenada y el orden de los partidos no la cambia.
- **Pruebas de contrato.** Schemathesis lee el OpenAPI y bombardea cada ruta con entradas válidas e inválidas.
  En su primera corrida **encontró cinco defectos reales**, todos corregidos y cubiertos por pruebas:
  1. Los `405` no llevaban la cabecera `Allow` (la exige RFC 9110).
  2. El OpenAPI documentaba los errores como `application/json`, pero salían como `application/problem+json`.
  3. Los `500` perdían el `X-Request-ID`, porque los atiende un middleware externo.
  4. `include_season: 0` se aceptaba como `false`, y el contrato dice `boolean`.
  5. Un cuerpo que no era JSON devolvía `404` en vez de `400`.

  Un sexto salió al probar a mano el despliegue: `HEAD` respondía `405` (RFC 9110 obliga a aceptarlo donde se
  acepta `GET`). Schemathesis no lo cubre porque `HEAD` no figura en el OpenAPI. Ahora tiene su prueba.

  Un séptimo apareció en producción el 2026-10-02: las respuestas salían con `Cache-Control: public`, así que el
  CDN de Vercel las guardaba cinco minutos con todas sus cabeceras y servía **el mismo `X-Request-ID` a todos**,
  ignorando el que mandara cada cliente. Ninguna prueba lo veía, porque corren contra la aplicación sin el CDN en
  medio, y la del `X-Request-ID` solo miraba `/health`, la única ruta que no se cachea. Ahora es `private` y hay
  pruebas sobre todas las rutas cacheables.

  Solo en la simulación se desactiva el chequeo de "datos válidos aceptados". JSON Schema no puede expresar
  "a 25 con 2 de ventaja", así que un 0-0 cumple el esquema y aun así debe rechazarse.

El CI (GitHub Actions) corre el linter, el formato y toda la batería en cada push, con Python 3.12 (el de producción) y 3.14. También publica la cobertura
y el informe JUnit como artefacto. Si la cobertura baja del 95 %, falla.

## Ejecutar en local

Las dependencias están en `pyproject.toml`, fijadas en `uv.lock`. Hace falta [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
uv run pytest --cov=app
```

## Los datos

`data/temporada-2026.json` se genera con `scripts/export_seed.py` a partir de la temporada congelada de la app
del torneo (`src/data/archivo-2026.json`), que quedó fija al terminar la temporada. Solo exporta equipos,
jornadas, partidos, parciales y la fase final.

**La fase final no tiene marcador.** Se jugó sin anotar los puntos, así que de cada partido solo se sabe quién
ganó. La API lo dice así (`score_recorded: false`) en vez de inventar un resultado. Al arrancar comprueba que el
cuadro cuadre con la liga: los semifinalistas son los cuatro primeros, por el 3.er puesto juegan los perdedores de
semifinal y la final, los ganadores. La fase final no suma a la tabla de la liga. **No incluye jugadores ni ningún
otro dato personal** (Ley 81 de Panamá): la API es pública y esas personas no aceptaron salir en ella.

## Autor

David Ameth Martínez Sánchez, ingeniero de control de calidad (QA): [davidameth.dev](https://davidameth.dev).

Licencia MIT.
