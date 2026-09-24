"""
Valida los CSV de data/ y los carga en PostgreSQL (esquema "cartera").

Si alguna validación falla, no se carga nada: mejor un informe sin
actualizar que un informe con datos incorrectos.

Requisitos:
    pip install "psycopg[binary]"

Uso (la contraseña se lee de la variable PGPASSWORD):
    set PGPASSWORD=tu_contraseña
    python python/cargar_postgres.py
"""
import csv
import os
import sys
from datetime import date
from pathlib import Path

import psycopg

DATA = Path(__file__).resolve().parent.parent / "data"

CONEXION = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "cartera"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD"),
)

# orden de carga: primero las tablas a las que apuntan las claves foráneas
TABLAS = ["clientes", "proyectos", "hitos", "sprints", "imputaciones"]


def leer(tabla):
    with open(DATA / f"{tabla}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validar(datos):
    errores = []

    ids_cliente = {r["cliente_id"] for r in datos["clientes"]}
    ids_proyecto = {r["proyecto_id"] for r in datos["proyectos"]}

    for tabla, filas in datos.items():
        clave = next(iter(filas[0]))  # la primera columna es siempre la clave
        ids = [r[clave] for r in filas]
        if len(ids) != len(set(ids)):
            errores.append(f"{tabla}: claves duplicadas en {clave}")

    for r in datos["proyectos"]:
        if r["cliente_id"] not in ids_cliente:
            errores.append(f"proyecto {r['codigo']}: cliente {r['cliente_id']} no existe")
        if date.fromisoformat(r["fecha_fin_plan"]) <= date.fromisoformat(r["fecha_inicio"]):
            errores.append(f"proyecto {r['codigo']}: fin planificado anterior al inicio")

    for tabla in ("hitos", "sprints", "imputaciones"):
        huerfanos = {r["proyecto_id"] for r in datos[tabla]} - ids_proyecto
        if huerfanos:
            errores.append(f"{tabla}: proyectos inexistentes {sorted(huerfanos)[:5]}")

    for r in datos["sprints"]:
        if int(r["puntos_completados"]) > int(r["puntos_comprometidos"]):
            errores.append(f"sprint {r['sprint_id']}: completados > comprometidos")

    horas_malas = sum(1 for r in datos["imputaciones"] if not 0 < float(r["horas"]) <= 12)
    if horas_malas:
        errores.append(f"imputaciones: {horas_malas} filas con horas fuera de rango (0, 12]")

    return errores


def cargar(datos):
    with psycopg.connect(**CONEXION) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO cartera")
        # vaciar en orden inverso por las claves foráneas
        cur.execute("TRUNCATE " + ", ".join(reversed(TABLAS)))
        for tabla in TABLAS:
            filas = datos[tabla]
            columnas = list(filas[0])
            with cur.copy(f"COPY {tabla} ({', '.join(columnas)}) FROM STDIN") as copy:
                for r in filas:
                    copy.write_row([r[c] if r[c] != "" else None for c in columnas])
            print(f"  {tabla:<13} {len(filas):>8} filas")
        # una sola transacción: si algo falla, no queda nada a medias
        conn.commit()


def main():
    datos = {t: leer(t) for t in TABLAS}

    errores = validar(datos)
    if errores:
        print("Validación fallida, no se carga nada:")
        for e in errores:
            print("  -", e)
        sys.exit(1)

    print("Validación correcta. Cargando en PostgreSQL...")
    cargar(datos)
    print("Carga terminada.")


if __name__ == "__main__":
    main()
