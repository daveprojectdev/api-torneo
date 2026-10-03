# Seguridad

## Reportar una vulnerabilidad

Si encuentras un problema de seguridad en la API (`api.davidameth.dev`) o en este
repositorio, escríbeme a **hola@davidameth.dev** con el asunto «Seguridad: api-torneo».
Por favor no abras un *issue* público mientras no esté corregido.

Incluye, si puedes, la ruta afectada, la petición que lo reproduce y el `X-Request-ID`
de la respuesta: con ese identificador encuentro la petición exacta.

Respondo en un plazo de 3 días hábiles. Lo que se confirme se corrige, se cubre con una
prueba que lo reproduce y se cuenta en el README, como los siete defectos anteriores.

## Alcance

- La API pública: solo lectura, sin cuentas ni datos personales. Sirve los resultados de
  una temporada de volleyball ya cerrada.
- `POST /v1/standings/simulate`: calcula una tabla con resultados hipotéticos y no guarda
  nada.

Fuera de alcance: la disponibilidad de Vercel, el CDN de jsDelivr que carga la
documentación de `/docs` y el volumen de peticiones (no hay límite por cliente, y está
declarado como deuda técnica en `docs/arquitectura-tecnica.md`).

---

**English:** to report a security issue, email hola@davidameth.dev with the subject
“Security: api-torneo”. Please don't open a public issue until it's fixed.
