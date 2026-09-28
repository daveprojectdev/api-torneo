"""Genera data/temporada-2026.json a partir del volcado de la base del torneo.

Uso:
    python scripts/export_seed.py "<ruta>/torneo-volleyball-2026/backups/torneo.sql"

Solo se exportan equipos, jornadas, partidos y parciales. Se dejan fuera a
propósito los jugadores, el jugador destacado, la asistencia y las notas:
la API es pública y esos datos son de personas reales (Ley 81 de Panamá).

Los identificadores de la base son UUID; la API usa otros legibles
(`aguilas-carmesi`, `j3-p2`). El guion falla si algo no cuadra en vez de
exportar un archivo a medias.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

INSERT = re.compile(r'^INSERT INTO "public"\."(\w+)" \((.*?)\) VALUES \((.*)\);$')
VALUE = re.compile(r"'((?:[^']|'')*)'|(NULL)|(-?\d+(?:\.\d+)?)")

TABLES = {"teams", "jornadas", "matches", "set_scores"}


def parse_values(raw: str) -> list[str | int | None]:
    out: list[str | int | None] = []
    for text, null, num in VALUE.findall(raw):
        if null:
            out.append(None)
        elif num:
            out.append(int(num) if "." not in num else num)
        else:
            out.append(text.replace("''", "'"))
    return out


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def read_dump(path: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {t: [] for t in TABLES}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = INSERT.match(line)
        if not m or m.group(1) not in TABLES:
            continue
        cols = [c.strip().strip('"') for c in m.group(2).split(",")]
        vals = parse_values(m.group(3))
        if len(cols) != len(vals):
            sys.exit(f"columnas y valores no cuadran en {m.group(1)}: {line[:120]}")
        rows[m.group(1)].append(dict(zip(cols, vals, strict=True)))
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rows = read_dump(Path(sys.argv[1]))

    teams = sorted(rows["teams"], key=lambda t: t["seed"])
    team_id = {t["id"]: slug(t["name"]) for t in teams}
    jornadas = sorted(rows["jornadas"], key=lambda j: j["number"])
    jornada_num = {j["id"]: j["number"] for j in jornadas}

    sets_by_match: dict[str, list[dict]] = {}
    for s in rows["set_scores"]:
        sets_by_match.setdefault(s["match_id"], []).append(s)

    matches = []
    for m in rows["matches"]:
        number = jornada_num[m["jornada_id"]]
        parciales = sorted(sets_by_match.get(m["id"], []), key=lambda s: s["set_number"])
        matches.append(
            {
                "id": f"j{number}-p{m['position_in_jornada']}",
                "jornada": number,
                "position": m["position_in_jornada"],
                "home": team_id[m["team1_id"]],
                "away": team_id[m["team2_id"]],
                "status": m["status"],
                "sets": [[s["points_team1"], s["points_team2"]] for s in parciales],
            }
        )
    matches.sort(key=lambda m: (m["jornada"], m["position"]))

    if len({m["id"] for m in matches}) != len(matches):
        sys.exit("hay dos partidos con la misma jornada y posición")

    seed = {
        "tournament": {
            "id": "torneo-volleyball-2026",
            "name": "Torneo Volleyball 2026",
            "format": "Liga todos contra todos, 3 sets fijos por partido",
            "source": "Volcado de la base de producción del torneo",
        },
        "teams": [{"id": team_id[t["id"]], "name": t["name"], "seed": t["seed"]} for t in teams],
        "jornadas": [
            {"number": j["number"], "name": j["name"], "date": j["date"], "city": j["city"]} for j in jornadas
        ],
        "matches": matches,
    }

    out = Path(__file__).resolve().parent.parent / "data" / "temporada-2026.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(teams)} equipos, {len(jornadas)} jornadas, {len(matches)} partidos -> {out}")


if __name__ == "__main__":
    main()
