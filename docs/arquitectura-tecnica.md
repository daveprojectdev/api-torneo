# Arquitectura Técnica — API Pública de Resultados de una Liga de Volleyball

**Autor:** David Ameth Martínez Sánchez · Ingeniero de QA · Panamá
**Cliente:** liga de volleyball de la Iglesia Adventista, Distrito Eclesiástico de Río Hato
(la API publica sus datos; la liga no la encargó)
**Naturaleza:** proyecto propio de portafolio · un solo mantenedor · código abierto (MIT)
**Versión:** 1.0 — 2 de octubre de 2026 · estado: en producción en `api.davidameth.dev`,
temporada 2026 cerrada y congelada

> Este documento organiza el sistema por dominios de arquitectura, no por cronología de
> desarrollo. Los siete defectos que se encontraron no aparecen como una lista de bugs: se
> agrupan en la Sección 4 por el supuesto equivocado que los produjo, porque casi ninguno
> fue un descuido de código. Las decisiones de diseño y las alternativas descartadas viven
> en los Registros de Decisiones Arquitectónicas (Apéndice C). La cronología, commit por
> commit, está en el historial del repositorio `daveprojectdev/api-torneo`.

---

## Resumen ejecutivo

La API sirve los resultados reales de una liga de volleyball de siete equipos: partidos set
a set, la tabla de posiciones y el podio de la fase final. Mirada por encima parece un CRUD
de solo lectura sobre un archivo JSON de 10 KB. No lo es: el archivo es lo único simple del
sistema, y la API resuelve tres problemas que no se ven desde fuera.

El primero es de **verificación sin un segundo par de ojos**. La tabla ya la calcula la
plataforma del torneo, en TypeScript, y la usan jugadores y afición desde junio. La API la
calcula otra vez, en Python, sin compartir una línea de código con la primera, y una prueba
exige que las dos coincidan en cada número de cada fila. Dos implementaciones
independientes que llegan al mismo resultado son la forma más barata de auditar un
cálculo cuando no hay nadie más que lo revise (ADR-001).

El segundo es de **un contrato que dice la verdad**. Una API pública se lee por su
documento OpenAPI, y el que genera el framework por defecto miente en los detalles: declara
errores con un tipo de contenido que no es el que sale, no anuncia métodos que acepta y
acepta valores que su propio esquema prohíbe. Las pruebas de contrato encontraron cinco de
esas mentiras en su primera corrida (Sección 4).

El tercero es de **datos que no admiten resultados imposibles**. Las reglas del voleibol
—sets a 25 con dos de ventaja, tres sets fijos, un cuadro final que tiene que cuadrar con la
liga— se aplican al archivo de datos al arrancar y a cada resultado simulado. Con un 25-24
en el archivo, el servidor no arranca.

---

## Índice

1. Arquitectura Core
2. Integridad de los Datos
3. El Contrato HTTP
4. Patrones de Resiliencia
5. Estrategia de Pruebas
6. Despliegue y Operación
7. Deuda Técnica y Huecos Conocidos

**Apéndices**
- A. Cronología condensada
- B. Referencia rápida
- C. Registros de Decisiones Arquitectónicas

---

## 1. Arquitectura Core

### 1.1 Modelo de datos

```
temporada-2026.json  (10.350 B, una foto fija)
    │
    ├── teams ─────── 7 equipos, con su siembra
    │
    ├── jornadas ──── 7 fechas ──── matches ──── 21 partidos · 63 sets
    │
    └── final_phase ─ 4 partidos sin marcador ──── podio
```

| Entidad | Campos relevantes | Volumen |
|---|---|---|
| `Team` | `id` legible (`aguilas-carmesi`), `name`, `seed` | 7 |
| `Jornada` | `number`, `date`, `city` · el estado no se guarda (ver 1.3) | 7 |
| `Match` | `id` (`j3-p2` = jornada 3, posición 2), `home`, `away`, `status`, `sets` | 21 |
| Parciales | pares `[local, visitante]`, tres por partido | 63 |
| `FinalMatch` | `round`, `home`, `away`, `winner` · sin puntos | 4 |

La base es pequeña a propósito y lo seguirá siendo: la temporada terminó el 26 de
septiembre de 2026 y no va a crecer. **La dificultad no está en la escala, está en las
reglas.** Siete equipos en todos contra todos dan 21 partidos, y con eso basta para que
aparezcan empates a puntos que se resuelven en el segundo criterio, ratios infinitos y un
podio que contradice la tabla (ver 1.4 y 1.5).

### 1.2 Componentes y rutas

El código se reparte en tres capas que no se mezclan:

| Archivo | Líneas | Responsabilidad |
|---|---|---|
| `app/domain.py` | 228 | Reglas del voleibol en funciones puras. No conoce HTTP ni JSON |
| `app/data.py` | 135 | Lee el archivo una vez y lo pasa entero por las reglas del dominio |
| `app/main.py` | 567 | Rutas, errores, cabeceras y el documento OpenAPI |
| `app/schemas.py` | 191 | Contratos de entrada y salida (Pydantic, modo estricto) |

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/v1/teams` · `/v1/teams/{id}` | Equipos en orden de siembra |
| GET | `/v1/jornadas` · `/v1/jornadas/{n}` | Fechas de juego, con su estado derivado |
| GET | `/v1/matches` | Partidos con filtros `jornada`, `team`, `status` y paginación |
| GET | `/v1/matches/{id}` | Un partido set a set |
| GET | `/v1/standings?through_jornada=n` | La tabla actual, o como quedó al cerrar la jornada `n` |
| POST | `/v1/standings/simulate` | La tabla con resultados hipotéticos. No guarda nada |
| GET | `/v1/final-phase` | Semifinales, 3.er puesto, final y podio |
| GET | `/health` · `/problems/{tipo}` | Salud del servicio y catálogo de errores |

Que el dominio no importe nada de FastAPI no es una preferencia de estilo: es lo que
permite que las 33 pruebas de reglas corran sin levantar un servidor, y que Hypothesis
genere 300 temporadas al azar en cada corrida contra las mismas funciones que usa
producción (Sección 5).

### 1.3 Lo que se calcula en vez de guardarse

**La tabla de posiciones no existe en ningún archivo.** Se calcula en cada petición a
partir de los 63 parciales. Lo mismo el número de sets que ganó cada equipo, el ganador de
cada partido y el estado de cada jornada (`pending`, `in_progress`, `completed`, según el
estado de sus partidos).

La regla viene de la plataforma del torneo, que la aprendió en producción: el conteo de
sets guardado junto al partido llegó a contradecir los parciales guardados aparte, y la
tabla se movía según cuál de los dos se leyera. Desde entonces los sets se derivan de los
parciales. La API nace con esa regla en vez de redescubrirla (ADR-002).

El costo se acepta a sabiendas: cada `GET /v1/standings` recorre los 21 partidos. Con este
volumen el cálculo no aparece en las mediciones (ver 6.3); el día que hubiera miles de
partidos, sería lo primero que habría que guardar.

### 1.4 Reglas que no son las intuitivas

**Tres sets fijos, no al mejor de tres.** Se juegan los tres sets aunque un equipo gane los
dos primeros, así que existen el 3-0 y el 2-1 como resultados distintos.

**Puntos FIVB, no victorias.** Ganar 3-0 da 3 puntos, ganar 2-1 da 2, perder 1-2 da 1 y
perder 0-3 da 0. Por eso un equipo con más victorias puede tener menos puntos.

**Desempate en cuatro escalones:** puntos, partidos ganados, ratio de sets, ratio de
puntos. El caso real de la temporada muestra por qué el segundo escalón importa:

| Pos. | Equipo | Puntos | Ganados | Sets |
|---|---|---|---|---|
| 2 | Little Giant | 11 | 4 | 11-7 |
| 3 | Centinelas de Luz | 11 | 3 | 11-7 |

Empatados a puntos y con los mismos sets, los separa haber ganado un partido más. La API
no se limita a ordenar: cada fila empatada lleva un campo `tiebreak` que lo dice en texto,
*"Empate a 11 pts; desempata partidos ganados"*, para que quien lee la tabla no tenga que
reconstruir el criterio.

**Que sean ratios y no totales es deliberado.** Un ratio sin nada perdido es infinito, y
JSON no tiene `Infinity`. La respuesta lleva `won`, `lost` y `ratio: null` en ese caso: el
número que no se puede escribir se omite en vez de sustituirse por uno inventado como
`999`.

### 1.5 Una fase final sin marcador

La liga terminó con cuatro partidos a eliminación entre los cuatro primeros: dos
semifinales, el 3.er puesto y la final. **Se jugaron sin anotar los puntos.** De cada
partido solo se sabe quién ganó.

La API lo declara en vez de taparlo: `/v1/final-phase` lleva `score_recorded: false` y
ningún set. Inventar un 3-0 plausible habría sido indetectable y falso.

El resultado es contraintuitivo y la API lo expone tal cual: **el líder de la liga terminó
cuarto en el podio.** Generación de Fe acabó la temporada regular primera con 12 puntos y
perdió su semifinal y el partido por el 3.er puesto; Centinelas de Luz, tercera en la
liga, fue campeona. Por eso el podio y la tabla son recursos separados y la fase final no
suma a la tabla.

---

## 2. Integridad de los Datos

### 2.1 De dónde salen

```
App del torneo (congelada el 28/09)
  src/data/archivo-2026.json  +  src/data/index.ts
            │
            ▼
  scripts/export_seed.py ──── falla si algo no cuadra; no exporta a medias
            │
            ▼
  data/temporada-2026.json (en el repo) ──── load_season() al arrancar
```

La plataforma del torneo dejó de hablar con su base de datos el 28 de septiembre de 2026:
la temporada quedó fija en un archivo dentro de su propio código. Esa es la fuente de la
API. El exportador traduce los números de equipo a identificadores legibles y **deja fuera,
a propósito, a los jugadores, el MVP, la asistencia, las notas y los testimonios**. La API
es pública y esos datos son de personas reales que no aceptaron salir en ella; la Ley 81 de
2019 de Panamá exige ese consentimiento.

### 2.2 Las reglas se aplican también a los datos propios

Cada partido marcado como completado se construye como un `MatchResult` del dominio al
cargar el archivo, y el constructor valida cada set:

```python
if win > SET_TARGET and win - lose != MIN_LEAD:
    raise InvalidScore(f"{home}-{away}: pasado de 25, el set termina en cuanto hay 2 de ventaja")
```

Un 25-24, un 27-24 o un partido con dos sets en el archivo impiden que el servidor
arranque. **Que un dato propio falle ruidosamente es la intención**: el archivo se edita a
mano o con un guion, y un error que solo se viera al pedir la tabla llegaría primero a un
usuario. Las pruebas de `test_datos.py` construyen archivos rotos a propósito —una jornada
o un equipo que no existen, un marcador imposible, un cuadro final que no cuadra— y exigen
que la carga se niegue; otra exige que el archivo real cargue.

### 2.3 El cuadro final se valida contra la liga

Al cargar la fase final, la API calcula la tabla de la liga y comprueba cuatro cosas antes
de aceptar el podio: que los semifinalistas sean exactamente los cuatro primeros, que
ningún equipo juegue las dos semifinales, que por el 3.er puesto jueguen los perdedores de
semifinal y que la final la jueguen los ganadores. Un cuadro que no cuadre no se publica:
la API no arranca.

---

## 3. El Contrato HTTP

Una API pública no tiene interfaz que explique nada: el contrato es la interfaz. Estas son
las decisiones que lo forman y la razón de cada una.

| Decisión | Qué hace | Por qué |
|---|---|---|
| Errores RFC 9457 | `application/problem+json` con `type`, `title`, `status`, `detail`, `instance`, `request_id` | Un formato estándar que un cliente puede tratar sin leer este documento (ADR-004) |
| Catálogo de errores | Cada `type` resuelve en `/problems/{tipo}` | El `type` es una URL; una URL que no lleva a ningún sitio es un identificador a medias |
| Validación estricta | `extra="forbid"` y `strict=True` | `0` no es `false` ni `"25"` es un número. Las conversiones silenciosas esconden clientes rotos |
| `ETag` y `304` | Hash SHA-256 del cuerpo; `If-None-Match` devuelve `304` sin cuerpo | Los datos no cambian; el cliente no debería volver a descargar 1.713 B de tabla |
| `Cache-Control: private` | Solo el navegador guarda la respuesta | Con `public`, el CDN repetía la respuesta entera a otros clientes (ver 4.1 y ADR-005) |
| `X-Request-ID` | En toda respuesta, incluidos los `500`; si el cliente manda uno, se respeta | Un error sin identificador no se puede buscar en los registros |
| `HEAD` | Se atiende como `GET` sin cuerpo | RFC 9110 lo exige donde se acepta `GET`; FastAPI no lo hace solo (ver 4.3) |
| Búsqueda vacía | `200` con lista vacía, no `404` | El `404` es para un recurso concreto que no existe, no para una búsqueda sin resultados |
| Versión en la ruta | `/v1/...` | Cambiar un campo de la tabla no debería romper a quien ya la consume |
| CORS abierto | `allow_origins=["*"]` | Es una API pública de solo lectura sin credenciales; restringir orígenes no protegería nada |

La documentación se sirve tres veces desde el mismo `/openapi.json`: Scalar en `/docs`,
Swagger UI en `/swagger` y ReDoc en `/redoc`. Ninguna está escrita a mano; si el contrato
cambia, las tres cambian con él.

⚠️ **Una consecuencia de la validación estricta que muerde al probar a mano:** un cuerpo
con un campo de más (`"comentario": "..."`) devuelve `422`, no se ignora. Es el
comportamiento correcto para un contrato, y es lo primero que sorprende a quien prueba la
API desde Postman copiando un ejemplo de otro lado.

---

## 4. Patrones de Resiliencia

Siete defectos que, contados por encima, parecen bugs sueltos. Contados con precisión,
salen de cuatro supuestos equivocados. Cinco los encontraron las pruebas de contrato en su
primera corrida, uno una prueba manual del despliegue y el último una medición hecha al
escribir este documento.

### 4.1 Se asumía que cada respuesta la genera la API

**Qué se asumía mal.** Que toda respuesta que llega al cliente sale del código de la API,
y que por eso cada una lleva su propio `X-Request-ID`.

**Por qué sobrevivió sin dar la cara.** Las respuestas cacheables salían con
`Cache-Control: public, max-age=300`, y `public` autoriza a cualquier caché compartida a
guardarlas. El CDN de Vercel lo hizo: guardaba la respuesta entera, cabeceras incluidas,
durante cinco minutos. Medido el 2 de octubre de 2026, tres peticiones seguidas a
`/v1/standings` recibieron el mismo identificador con `X-Vercel-Cache: HIT`, y una petición
que mandó el suyo propio recibió el de otro cliente.

Ninguna de las 90 pruebas que había lo vio, por dos razones que se suman. Todas corren
contra la aplicación en proceso, sin el CDN en medio, así que la capa donde estaba el
defecto no existía para ellas. Y la única prueba del `X-Request-ID` miraba `/health`, que
es justamente la única ruta que no se cachea.

**Qué lo resolvió.** `Cache-Control: private, max-age=300`: el navegador sigue guardando
la respuesta y haciendo peticiones condicionales con `ETag`, pero ninguna caché compartida
puede hacerlo. Diez pruebas nuevas recorren las cinco rutas cacheables y exigen que
respeten el identificador del cliente y que ninguna lleve `public` ni `s-maxage`. El costo
medido es nulo desde Panamá: sin CDN el tiempo hasta el primer byte quedó entre 0,25 y
0,35 s, contra 0,22 a 0,37 s con él (ADR-005).

**Regla general.** Una prueba que no atraviesa las mismas capas que el tráfico real no
puede ver los defectos que viven en esas capas. Y una cabecera que es distinta en cada
petición no puede viajar en una respuesta que una caché compartida tiene permiso de
guardar.

### 4.2 Se asumía que el documento que genera el framework describe lo que hace

**Qué se asumía mal.** Que el OpenAPI que FastAPI genera es una descripción fiel de la API,
porque sale del mismo código.

**Por qué sobrevivió sin dar la cara.** Sale del mismo código, pero de las declaraciones,
no del comportamiento. FastAPI documentaba los errores como `application/json` con su
propio esquema de validación, mientras los manejadores de error los emitían como
`application/problem+json` con otro. Leído en Swagger, el documento se veía correcto; solo
una herramienta que compara cada respuesta con lo que el documento promete podía notarlo.

**Qué lo resolvió.** El OpenAPI se reescribe una vez para todas las rutas: cada `4xx` y
`5xx` declara `application/problem+json` con el esquema `Problem`, y los esquemas de error
que FastAPI añade por su cuenta se eliminan. Desde entonces Schemathesis valida cada
respuesta contra el documento en cada corrida del CI.

**Regla general.** Un documento generado describe las intenciones del código, no su
comportamiento. Solo se vuelve verdadero cuando algo lo contrasta con las respuestas.

### 4.3 Se asumía que lo que el framework no hace, nadie lo pide

**Qué se asumía mal.** Que los detalles de HTTP que el framework no resuelve solo son
casos raros que ningún cliente real va a ejercitar.

**Por qué sobrevivió sin dar la cara.** Tres defectos comparten este origen. Los `405`
salían sin la cabecera `Allow` que RFC 9110 exige. `HEAD` respondía `405` en vez de
comportarse como `GET`, y **Schemathesis no podía verlo porque `HEAD` no figura en el
OpenAPI**: lo encontró una prueba manual del despliegue con `curl -I`, que usa `HEAD` por
defecto. Y un cuerpo que no era JSON devolvía `404` en vez de `400`, porque el manejador de
errores convertía en «no encontrado» todo lo que no reconocía.

**Qué lo resolvió.** Un middleware que atiende `HEAD` como `GET` y descarta el cuerpo al
enviarlo, para que `Content-Length` y `ETag` sean los mismos. El manejador de errores
conserva el código original en vez de traducirlo, y pasa las cabeceras de la excepción, que
es donde Starlette ya traía `Allow`.

**Regla general.** Las pruebas generadas desde un contrato solo cubren lo que el contrato
declara. Lo que el estándar exige y el contrato no menciona necesita una prueba escrita a
mano.

### 4.4 Se asumía que un manejador de errores es el último en ver la petición

**Qué se asumía mal.** Dos supuestos del mismo tipo: que el middleware que pone el
`X-Request-ID` corre para todas las respuestas, y que el modo de validación por defecto de
Pydantic aplica el contrato tal como está escrito.

**Por qué sobrevivió sin dar la cara.** Los `500` los atiende el `ServerErrorMiddleware` de
Starlette, que envuelve a todos los demás middlewares, así que esas respuestas salían
**sin** `X-Request-ID`: precisamente las únicas en las que el identificador hace falta.
Y en modo permisivo Pydantic aceptaba `include_season: 0` como `false`, aunque el esquema
publicado dice `boolean`. Ninguno de los dos se ve en un uso normal: hace falta provocar un
error interno o mandar un tipo equivocado a propósito, que es exactamente lo que hace una
herramienta de contrato.

**Qué lo resolvió.** La función que construye cada error pone el `X-Request-ID` ella misma,
en vez de confiar en el middleware. Y todos los esquemas de entrada pasan a `strict=True`.

**Regla general.** Una garantía que dependa del orden de los middlewares no es una
garantía. Se pone en el punto por donde pasan todas las respuestas que la necesitan.

---

## 5. Estrategia de Pruebas

### 5.1 Cinco capas, cada una ve algo que las otras no

| Capa | Archivo | Pruebas | Qué encuentra que las demás no pueden |
|---|---|---|---|
| Dominio y propiedades | `test_dominio.py` | 33 | Errores en las reglas, en temporadas que nadie escribió a mano |
| API | `test_api.py` | 46 | Filtros, paginación, códigos, cabeceras, `HEAD`, caché |
| Datos | `test_datos.py` | 8 | Archivos de temporada imposibles que se negarían a cargar |
| Contrato | `test_contrato.py` | 11 | Diferencias entre lo que promete el OpenAPI y lo que responde la API |
| Oráculo | `test_oraculo_produccion.py` | 2 | Un error de cálculo compartido por todas las capas anteriores |

Son **100 pruebas** con **99,44 % de cobertura** de líneas y ramas, en unos 18 s en local.
El CI falla si la cobertura baja del 95 %.

### 5.2 El oráculo: dos implementaciones que no comparten código

Las pruebas de dominio comprueban que el código hace lo que el autor cree que dicen las
reglas. No pueden detectar que el autor entendió mal una regla, porque la prueba y el
código nacen del mismo entendimiento.

El oráculo cubre ese hueco. La tabla y el podio que publicó la plataforma del torneo se
copiaron a mano el 27 y el 28 de septiembre de 2026, y la prueba exige que la API produzca
exactamente los mismos siete renglones: posición, partidos jugados y ganados, sets, puntos
anotados y recibidos y puntos de tabla. La plataforma calcula en TypeScript y la API en
Python, sin compartir una línea; si discrepan en un solo número, una de las dos está mal.
**Coincidió a la primera.**

### 5.3 Propiedades en vez de ejemplos

Hypothesis genera 300 temporadas al azar por corrida, de cero a treinta partidos con
parciales válidos, y comprueba invariantes que tienen que cumplirse en cualquiera de ellas
(el desorden de los partidos se prueba aparte, con 150 casos): cada partido reparte
exactamente tres puntos de tabla, los sets ganados de la liga suman lo mismo que los
perdidos, la tabla sale ordenada según los cuatro criterios y el orden en que llegan los
partidos no la cambia. Un ejemplo escrito a mano prueba un caso; una propiedad prueba la
regla.

### 5.4 Contrato, con una exclusión declarada

Schemathesis lee el OpenAPI y genera peticiones válidas e inválidas para cada operación,
cuarenta por ruta. Comprueba códigos declarados, tipos de contenido, cuerpos y la cabecera
`Allow`, y que nunca salga un `500`.

**En la simulación se desactiva un único chequeo, a propósito**: el que exige aceptar
datos que cumplen el esquema. JSON Schema no puede expresar «a 25 con dos de ventaja», así
que un 0-0 cumple el esquema y aun así tiene que rechazarse. Todos los demás chequeos
siguen activos en esa ruta.

### 5.5 Dónde se ve el resultado

Cada push a `main` corre el linter, el formato y la batería completa en Python 3.12 (el de
producción) y 3.14 (el de desarrollo), en unos 40 s. La corrida con 3.12 publica su
resultado, prueba por prueba, en `qa.davidameth.dev`, junto al de las pruebas end-to-end
del portafolio. Una corrida roja se ve ahí sin abrir GitHub.

---

## 6. Despliegue y Operación

### 6.1 Topología

```
cliente  →  CDN de Vercel (no guarda las respuestas: private)  →  función Python 3.12
                                                                      │
                                                    FastAPI + datos en memoria (10 KB)
```

`index.py`, en la raíz del repositorio, expone la aplicación para que Vercel la encuentre.
No hay base de datos, colas ni almacenamiento: el archivo de la temporada viaja con el
código y se lee una sola vez por instancia (`functools.cache`). Cada push a `main` en
GitHub despliega solo.

### 6.2 Las trampas de Python en Vercel

Vercel instala las dependencias con `uv` cuando encuentra un `pyproject.toml`, y en ese
caso **exige una tabla `[project]`**. El primer despliegue falló con las dependencias en
`requirements.txt` y el `pyproject.toml` reservado para herramientas; la solución fue
invertir el reparto: dependencias en `pyproject.toml`, fijadas en `uv.lock`, y ningún
`requirements.txt`. Así la misma lista la leen Vercel, el CI y el entorno local.

⚠️ **Producción corre Python 3.12 y el desarrollo local, 3.14.** En la máquina de
desarrollo, `uv` no instala 3.12 y el control de aplicaciones de Windows bloquea los
ejecutables de los entornos virtuales nuevos, así que las pruebas locales se lanzan con
`python -m pytest`. **La versión de producción solo se prueba en el CI**, con la matriz de
dos versiones; nadie la ha corrido a mano.

### 6.3 Cifras de operación

Medido el 2 de octubre de 2026 desde Panamá contra `api.davidameth.dev`, diez peticiones
por ruta:

| Medición | Valor |
|---|---|
| Primera petición tras un despliegue (arranque en frío) | 1,96 s hasta el primer byte |
| Peticiones siguientes | 0,22 – 0,36 s hasta el primer byte |
| Conexión TCP + TLS (de lo anterior) | 0,05 s + 0,12 s |
| `/v1/standings` | 1.713 B |
| `/v1/matches` (primera página, 10 partidos) | 3.390 B |
| `/v1/final-phase` | 1.280 B |
| Repetición con `If-None-Match` | `304`, 0 B de cuerpo |
| Región de la función | `iad1` (Washington, D. C.) |
| Costo de operación | $0/mes (plan gratuito de Vercel) |

Casi todo el tiempo de una petición es red: el cálculo de la tabla sobre 21 partidos no se
distingue en estas mediciones. La región es la que Vercel asigna por defecto y no se ha
cambiado.

---

## 7. Deuda Técnica y Huecos Conocidos

Esta sección existe para que el documento sea utilizable y no promocional.

| Asunto | Estado | Riesgo |
|---|---|---|
| Ninguna prueba atraviesa el CDN ni el despliegue real: todas corren contra la aplicación en proceso | Abierto | Alto para el próximo cambio de infraestructura: así sobrevivió el defecto de la Sección 4.1, y otro de la misma familia sobreviviría igual. Falta una prueba de humo contra `api.davidameth.dev` después de cada despliegue |
| Un marcador imposible en la simulación devuelve `type: validation`; `invalid-score` («Marcador imposible») solo sale cuando el equipo no existe | Abierto | Bajo, para un cliente que distinga errores por `type`: el nombre del tipo dice lo contrario de lo que pasa |
| `POST /v1/standings/simulate` no tiene límite de peticiones, solo un máximo de 200 resultados por cuerpo | Abierto | Bajo mientras el tráfico sea de portafolio; un bucle de un tercero consumiría el cupo gratuito de funciones de Vercel |
| Python 3.12, el de producción, solo se prueba en el CI (Sección 6.2) | Aceptado a conciencia | Medio: un fallo específico de 3.12 se ve después del push, no antes |
| El oráculo es una copia manual de la tabla de producción del 27 y 28 de septiembre | Aceptado a conciencia | Nulo mientras la temporada siga congelada; si la plataforma corrigiera un dato, el oráculo no lo sabría hasta copiarlo otra vez |
| `/docs` carga Scalar desde jsDelivr con la versión mayor `@1` sin fijar | Aceptado a conciencia | Bajo: una versión nueva de Scalar o una caída de jsDelivr dejan sin esa página, pero `/swagger`, `/redoc` y la API siguen funcionando |
| La fase final no tiene marcador | Dato faltante, no recuperable | Ninguno técnico: la API lo declara (`score_recorded: false`) y no lo inventa |
| Arranque en frío de 1,96 s en la primera petición | Aceptado a conciencia | Bajo: lo nota quien abre `/docs` después de un rato sin tráfico |

---

## Apéndice A — Cronología condensada

| Fecha (2026) | Etapa | Dónde vive en este documento |
|---|---|---|
| 27 sep | Primera versión: datos reales, tabla FIVB, simulación y 77 pruebas | Sección 1 · ADR-001, 002, 003 |
| 27 sep | Dependencias en `pyproject.toml` y `uv.lock` para Vercel | Sección 6.2 |
| 27 sep | `HEAD` como `GET`; cinco defectos de contrato corregidos | Secciones 4.2 a 4.4 · ADR-004 |
| 27 sep | Dominio propio `api.davidameth.dev` | Sección 6.1 |
| 28 sep | Fase final y podio, validados contra la liga; datos desde la temporada congelada | Secciones 1.5, 2.1 y 2.3 |
| 1 oct | Cada corrida del CI se publica en `qa.davidameth.dev` | Sección 5.5 |
| 2 oct | El CDN repetía el `X-Request-ID`: `Cache-Control: private` y 10 pruebas nuevas | Sección 4.1 · ADR-005 |

Son 13 commits en seis días. La historia completa está en el repositorio
`daveprojectdev/api-torneo`.

---

## Apéndice B — Referencia rápida

| Categoría | Dato |
|---|---|
| URL | `https://api.davidameth.dev` · documentación en `/docs`, `/swagger` y `/redoc` |
| Lenguaje | Python 3.12 en producción · 3.14 en desarrollo |
| Framework | FastAPI 0.141.1 · Pydantic 2.13.5 |
| Pruebas | pytest 9.1.1 · Hypothesis 6.168.2 · Schemathesis 4.28.0 · pytest-cov 7.1.0 |
| Calidad de código | Ruff 0.16.9, línea de 110 caracteres |
| Dependencias de producción | 2 (FastAPI y Pydantic) |
| Datos | 7 equipos · 7 jornadas · 21 partidos · 63 sets · 4 partidos de fase final · 10.350 B |
| Código | 1.121 líneas en `app/` · 694 líneas de pruebas |
| Pruebas | 100 · 99,44 % de cobertura · umbral del CI 95 % |
| Defectos encontrados | 7: 5 por pruebas de contrato, 1 a mano, 1 midiendo producción |
| Rendimiento | 0,22 – 0,36 s hasta el primer byte · 1,96 s en frío |
| Despliegue | Vercel, región `iad1`, despliegue automático desde `main` |
| CI | GitHub Actions, Python 3.12 y 3.14, unos 40 s |
| Errores | RFC 9457, seis tipos, catálogo en `/problems/{tipo}` |
| Datos personales | Ninguno (Ley 81 de 2019) |
| Costo de operación | $0/mes |
| Licencia | MIT |

---

## Apéndice C — Registros de Decisiones Arquitectónicas

### ADR-001 — Lenguaje y framework de la API

**Contexto.** La plataforma del torneo ya calcula la tabla en TypeScript, en una función
probada en producción durante toda la temporada. La API necesita el mismo cálculo y
además una documentación interactiva generada desde el código.

**Opciones consideradas.**
- *TypeScript con Hono.* El mismo lenguaje que la plataforma: la función de la tabla se
  podía copiar o importar tal cual. Hono corre en Vercel sin ajustes y es la opción con
  menos piezas nuevas.
- *Python con FastAPI.* Un lenguaje nuevo para el autor, que quería aprenderlo y
  practicarlo. FastAPI genera el OpenAPI desde los tipos y Pydantic valida con los mismos
  modelos que documenta.

**Decisión.** Python con FastAPI.

**Consecuencias.** El motivo fue aprender Python, y la consecuencia de más valor no se
buscó: al escribir la tabla otra vez, en otro lenguaje y sin reutilizar código, la API se
volvió una **segunda implementación independiente**, y eso es lo que da sentido a la
prueba oráculo (Sección 5.2). Con TypeScript, lo natural habría sido importar la función
de la plataforma, y el oráculo habría comparado el código consigo mismo. Lo que se perdió:
la regla de los sets y el desempate existen dos veces y cualquier cambio de reglamento hay
que hacerlo en las dos; el soporte de Python en Vercel es menos directo y costó un
despliegue fallido (Sección 6.2); y la versión de producción no se puede probar en la
máquina de desarrollo.

### ADR-002 — Guardar o calcular la tabla de posiciones

**Contexto.** La tabla depende de los sets de cada partido, y los sets se pueden leer de
dos lugares: un conteo guardado junto al partido o los parciales guardados aparte. En la
plataforma del torneo esos dos hechos llegaron a contradecirse.

**Opciones consideradas.**
- *Guardar la tabla ya calculada en el archivo de datos.* Respuestas sin cálculo, pero la
  tabla y los partidos serían dos hechos que se pueden desincronizar, que es el problema
  que la plataforma ya sufrió.
- *Guardar el conteo de sets y calcular la tabla a partir de él.* Menos cálculo que con
  parciales, pero conserva la misma doble fuente.
- *Calcular todo desde los parciales en cada petición.* Una sola fuente de verdad.

**Decisión.** Calcular desde los parciales en cada petición.

**Consecuencias.** No hay ninguna posición ni ningún conteo guardado que pueda contradecir
a los parciales, y la simulación reutiliza el mismo cálculo con resultados añadidos. **Lo
que se pierde:** cada petición paga el cálculo completo, recorriendo todos los partidos.
Con 21 no se mide (Sección 6.3), y la decisión debe revisarse si la API llegara a servir
más de una temporada o una liga con cientos de partidos.

### ADR-003 — Dónde viven los datos

**Contexto.** La plataforma del torneo guardaba la temporada en una base de datos
gestionada hasta que la congeló, el 28 de septiembre de 2026, en un archivo dentro de su
código. La API solo lee.

**Opciones consideradas.**
- *Leer de la base de datos de la plataforma.* Datos siempre al día, pero la API pública
  quedaría conectada a la base que guarda también jugadores y testimonios, con una
  credencial que proteger y una dependencia más para estar en línea.
- *Una base de datos propia.* Aislada de la plataforma, pero un servicio más que mantener
  para 10 KB que no cambian.
- *Un archivo JSON exportado, dentro del repositorio.* Sin conexión, sin credenciales y
  validado al arrancar.

**Decisión.** Un archivo JSON exportado, versionado junto al código.

**Consecuencias.** El despliegue no depende de ningún otro servicio, el archivo pasa por
las reglas del dominio antes de servirse (Sección 2.2) y queda fuera, por construcción,
todo dato personal (Sección 2.1). Se pierde la actualización automática: cualquier
corrección de un resultado exige volver a exportar y desplegar. Con la temporada cerrada
eso no ocurre; con una temporada en curso, esta decisión tendría que revisarse.

### ADR-004 — Formato de los errores

**Contexto.** FastAPI responde los errores con su propio formato (`{"detail": ...}`) y los
de validación con otro distinto. Una API pública necesita que un cliente pueda tratar
todos los errores de la misma forma.

**Opciones consideradas.**
- *El formato por defecto de FastAPI.* Cero trabajo, pero dos formas distintas según el
  tipo de error y ninguna estándar.
- *Un formato propio.* Uniforme, pero un cliente tendría que leer este documento para
  entenderlo.
- *RFC 9457 (`application/problem+json`).* Un estándar del IETF que los clientes HTTP ya
  saben tratar, con campos para extender.

**Decisión.** RFC 9457, con `request_id` y `errors` como extensiones.

**Consecuencias.** Todos los errores tienen la misma forma y cada `type` es una URL que
documenta el error. **Lo que se pierde:** el OpenAPI que genera FastAPI deja de describir
la API, porque sigue anunciando el formato por defecto. Hay que reescribirlo para todas
las rutas (Sección 4.2) y mantener esa reescritura en cada versión del framework. Sin
pruebas de contrato, esa discrepancia seguiría publicada.

### ADR-005 — Quién puede guardar las respuestas

**Contexto.** Los datos no cambian, así que cada respuesta se puede guardar. Al mismo
tiempo, cada respuesta lleva un `X-Request-ID` distinto por petición.

**Restricción no negociable.** Una respuesta que lleva un identificador por petición no
puede servírsele a otro cliente.

**Opciones consideradas.**
- *`public, max-age=300`.* El navegador y el CDN la guardan. El CDN responde sin despertar
  la función, pero repite la respuesta con sus cabeceras a todos los clientes durante cinco
  minutos.
- *`private, max-age=300`.* Solo el navegador la guarda y sigue haciendo peticiones
  condicionales con `ETag`.
- *Mantener `public` y quitar el `X-Request-ID` de las respuestas cacheables.* El CDN
  funciona, pero se rompe la promesa de trazabilidad en cinco de las rutas.

**Decisión.** `private, max-age=300`.

**Consecuencias.** Cada respuesta vuelve a tener su identificador y se respeta el del
cliente. Se pierde la caché del CDN, y con ella la posibilidad de servir sin despertar la
función. La medición dice que esa pérdida no se nota desde Panamá: 0,25 a 0,35 s sin CDN
contra 0,22 a 0,37 s con él (Sección 6.3). Si el tráfico creciera hasta que el costo de
las funciones importara, la opción correcta sería separar: guardar en el CDN un cuerpo sin
cabeceras por petición y añadir el identificador en el borde.

> **Revisión — 2 de octubre de 2026.** La primera versión usaba `public`. Se cambió al
> medir producción para escribir este documento, que encontró el defecto descrito en la
> Sección 4.1.
