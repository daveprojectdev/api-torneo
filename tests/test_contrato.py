"""Pruebas de contrato: Schemathesis genera peticiones a partir del OpenAPI.

Para cada operación documentada manda entradas válidas e inválidas y
comprueba que la respuesta cumpla lo que el propio OpenAPI promete: código
declarado, cuerpo y Content-Type declarados, `Allow` en los 405, y nunca un 500.

En su primera corrida encontró cuatro defectos reales, ya corregidos:
los 405 sin cabecera `Allow`, los errores documentados como application/json
cuando salían como application/problem+json, los 500 sin `X-Request-ID`, y
`include_season: 0` aceptado como `false`.
"""

import schemathesis
from hypothesis import settings
from schemathesis.specs.openapi.checks import positive_data_acceptance

from app.main import app

schema = schemathesis.openapi.from_asgi("/openapi.json", app)

# JSON Schema no puede expresar las reglas del voleibol ("a 25 con 2 de
# ventaja", "no contra sí mismo"). Un marcador como 0-0 cumple el esquema y
# aun así es imposible, así que en la simulación un 422 es la respuesta
# correcta a datos "válidos". Todos los demás chequeos siguen activos.
BUSINESS_RULES = {"POST /v1/standings/simulate"}


@schema.parametrize()
@settings(max_examples=40, deadline=None)
def test_la_api_cumple_su_openapi(case):
    excluded = [positive_data_acceptance] if case.operation.label in BUSINESS_RULES else []
    case.call_and_validate(excluded_checks=excluded)
