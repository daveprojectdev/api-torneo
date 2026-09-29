"""Genera data/temporada-2026.json a partir de la temporada congelada del torneo.

Uso:
    python scripts/export_seed.py "<ruta>/torneo-volleyball-2026"

Desde el 2026-09-28 la app del torneo ya no habla con Supabase: la temporada
quedó fija en `src/data/archivo-2026.json` (partidos y parciales), y los
nombres de equipos y jornadas viven en `src/data/index.ts`. Esas dos son la
fuente; el volcado SQL de `backups/` ya no se actualiza.

Solo se exportan equipos, jornadas, partidos, parciales y la fase final. Se
dejan fuera a propósito los jugadores, el MVP, la asistencia, las notas y los
testimonios: la API es pública y esos datos son de personas reales (Ley 81 de
Panamá).

En el archivo, cada equipo es un número que coincide con su siembra; la API
usa identificadores legibles (`aguilas-carmesi`, `j3-p2`). El guion falla si
algo no cuadra en vez de exportar un archivo a medias.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

# `  1: { id: 1, name: 'Águilas Carmesí', ...`
TEAM = re.compile(r"^\s+(\d+):\s*\{\s*id:\s*\1,\s*name:\s*'([^']+)'", re.M)
# `  { id: 'J3', number: 3, name: 'Jornada 3', date: '2026-07-11', city: 'San Carlos' },`
JORNADA = re.compile(
    r"\{\s*id:\s*'(\w+)',\s*number:\s*(\d+),\s*name:\s*'([^']+)',"
    r"(?:\s*corto:\s*'[^']*',)?\s*date:\s*'([^']*)',\s*city:\s*'([^']*)'(,\s*fase:\s*'final')?"
)

# Qué partido es cada posición de la fase final. En la app es un dato pactado
# (RONDAS_FASE_FINAL en src/data/index.ts), no algo que se deduzca.
ROUNDS = {1: "semifinal_1", 2: "semifinal_2", 3: "third_place", 4: "final"}
ROUND_NAMES = {1: "Semifinal 1", 2: "Semifinal 2", 3: "Por el 3.er puesto", 4: "Final"}


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    archivo = json.loads((root / "src/data/archivo-2026.json").read_text(encoding="utf-8"))
    index_ts = (root / "src/data/index.ts").read_text(encoding="utf-8")

    teams = [{"num": int(n), "id": slug(name), "name": name} for n, name in TEAM.findall(index_ts)]
    if len(teams) != 7:
        sys.exit(f"se esperaban 7 equipos en index.ts y salieron {len(teams)}")
    team_id = {t["num"]: t["id"] for t in teams}

    jornadas, final = [], None
    for _, number, name, date, city, is_final in JORNADA.findall(index_ts):
        if is_final:
            final = {"number": int(number), "date": date, "city": city}
        else:
            jornadas.append({"number": int(number), "name": name, "date": date or None, "city": city or None})
    if len(jornadas) != 7 or final is None:
        sys.exit(f"se esperaban 7 jornadas de liga y una fase final; salieron {len(jornadas)} y {final}")

    league, final_matches = [], []
    for m in archivo["matches"].values():
        if m["jornadaNumber"] == final["number"]:
            if m["winner"] not in (m["t1"], m["t2"]):
                sys.exit(f"fase final, posición {m['position']}: el ganador no jugó ese partido")
            final_matches.append(
                {
                    "id": f"ff-p{m['position']}",
                    "position": m["position"],
                    "round": ROUNDS[m["position"]],
                    "round_name": ROUND_NAMES[m["position"]],
                    "home": team_id[m["t1"]],
                    "away": team_id[m["t2"]],
                    "winner": team_id[m["winner"]],
                }
            )
            continue
        parciales = sorted(archivo["setScores"].get(m["id"], []), key=lambda s: s["n"])
        league.append(
            {
                "id": f"j{m['jornadaNumber']}-p{m['position']}",
                "jornada": m["jornadaNumber"],
                "position": m["position"],
                "home": team_id[m["t1"]],
                "away": team_id[m["t2"]],
                "status": m["status"],
                "sets": [[s["p1"], s["p2"]] for s in parciales],
            }
        )
    league.sort(key=lambda m: (m["jornada"], m["position"]))
    final_matches.sort(key=lambda m: m["position"])

    if len({m["id"] for m in league}) != len(league):
        sys.exit("hay dos partidos con la misma jornada y posición")
    if [m["position"] for m in final_matches] != [1, 2, 3, 4]:
        sys.exit("la fase final debe tener exactamente las posiciones 1 a 4")

    seed = {
        "tournament": {
            "id": "torneo-volleyball-2026",
            "name": "Torneo Volleyball 2026",
            "format": "Liga todos contra todos, 3 sets fijos por partido; fase final a eliminación",
            "source": f"Temporada congelada de la app del torneo ({archivo['congelado'][:10]})",
        },
        "teams": [{"id": t["id"], "name": t["name"], "seed": t["num"]} for t in teams],
        "jornadas": jornadas,
        "matches": league,
        "final_phase": {
            "date": final["date"],
            "city": final["city"],
            # Se jugó sin anotar los puntos: la app solo guardó quién ganó.
            "score_recorded": False,
            "matches": final_matches,
        },
    }

    out = Path(__file__).resolve().parent.parent / "data" / "temporada-2026.json"
    out.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(teams)} equipos, {len(jornadas)} jornadas, {len(league)} partidos de liga, "
        f"{len(final_matches)} de fase final -> {out}"
    )


if __name__ == "__main__":
    main()
