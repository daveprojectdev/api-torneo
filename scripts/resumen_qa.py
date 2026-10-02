"""Resume el JUnit y la cobertura de pytest para qa.davidameth.dev.

    uv run python scripts/resumen_qa.py reporte/junit.xml reporte/cobertura.json > resumen.json

Lo corre el CI al terminar las pruebas (solo en main y con Python 3.12, el de
producción) y sube el resultado al repo daveprojectdev/qa, que lo convierte en
una página. Solo usa la biblioteca estándar.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    junit, cobertura = Path(sys.argv[1]), Path(sys.argv[2])
    raiz = ET.parse(junit).getroot()
    grupos = [raiz] if raiz.tag == "testsuite" else raiz.findall("testsuite")

    total = sum(int(g.get("tests", 0)) for g in grupos)
    fallidas = sum(int(g.get("failures", 0)) + int(g.get("errors", 0)) for g in grupos)
    omitidas = sum(int(g.get("skipped", 0)) for g in grupos)
    duracion = sum(float(g.get("time", 0)) for g in grupos)

    fallos = []
    pruebas = []
    for g in grupos:
        for caso in g.iter("testcase"):
            fallo = caso.find("failure")
            if fallo is None:
                fallo = caso.find("error")
            if fallo is not None:
                fallos.append(f"{caso.get('classname')}::{caso.get('name')}")
            mensaje = (fallo.get("message") or "").strip().splitlines() if fallo is not None else []
            pruebas.append(
                {
                    "archivo": caso.get("classname", "").replace(".", "/") + ".py",
                    "titulo": caso.get("name"),
                    "proyecto": None,
                    "estado": "falla"
                    if fallo is not None
                    else "omitida"
                    if caso.find("skipped") is not None
                    else "pasa",
                    "ms": round(float(caso.get("time", 0)) * 1000),
                    "error": mensaje[0][:300] if mensaje else None,
                }
            )

    porcentaje = None
    if cobertura.exists():
        porcentaje = round(json.loads(cobertura.read_text())["totals"]["percent_covered"], 1)

    servidor = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, corrida = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")

    resumen = {
        "suite": "api-torneo",
        "fecha": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "resultado": "pasa" if fallidas == 0 else "falla",
        "pasadas": total - fallidas - omitidas,
        "fallidas": fallidas,
        "inestables": 0,
        "omitidas": omitidas,
        "duracion_s": round(duracion),
        "cobertura": porcentaje,
        "commit": os.environ.get("GITHUB_SHA", "")[:7] or None,
        "corrida": f"{servidor}/{repo}/actions/runs/{corrida}" if repo and corrida else None,
        "fallos": fallos[:25],
        "detalle": True,
        "pruebas": pruebas,
    }
    json.dump(resumen, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
