"""
Exporta las tres vistas de KPIs de PostgreSQL a un fichero DuckDB (datos_cartera.duckdb).

Así el asistente puede publicarse en la nube sin servidor de base de datos:
el fichero viaja con el código y DuckDB entiende el mismo SQL que PostgreSQL.
Usa el usuario de solo lectura del .env.

Ejecutar:  python asistente/exportar_duckdb.py
"""
import os
from pathlib import Path

import duckdb
import pandas as pd
import psycopg

CARPETA = Path(__file__).resolve().parent
DESTINO = CARPETA / "datos_cartera.duckdb"

for linea in (CARPETA / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linea and not linea.strip().startswith("#"):
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())

CONEXION = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "cartera"),
    user=os.getenv("PG_ASISTENTE_USER", "asistente_ro"),
    password=os.getenv("PG_ASISTENTE_PASSWORD"),
)
VISTAS = ["vw_estado_proyecto", "vw_velocidad_sprint", "vw_coste_mensual"]

if DESTINO.exists():
    DESTINO.unlink()

with psycopg.connect(**CONEXION) as pg:
    destino = duckdb.connect(str(DESTINO))
    destino.execute("CREATE SCHEMA cartera")
    for vista in VISTAS:
        with pg.cursor() as cur:
            cur.execute(f"SELECT * FROM cartera.{vista}")
            columnas = [c.name for c in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=columnas)
        # los NUMERIC de PostgreSQL llegan como Decimal: a float para DuckDB
        for col in df.columns:
            if df[col].map(lambda v: v.__class__.__name__ == "Decimal").any():
                df[col] = df[col].astype(float)
        destino.register("tmp", df)
        destino.execute(f"CREATE TABLE cartera.{vista} AS SELECT * FROM tmp")
        destino.unregister("tmp")
        print(f"{vista}: {len(df)} filas")
    destino.close()

print(f"OK -> {DESTINO} ({DESTINO.stat().st_size / 1024:.0f} KB)")
