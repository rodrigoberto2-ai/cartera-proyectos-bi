# Cartera de Proyectos — PostgreSQL · Python · Power BI

Cuadro de mando para el seguimiento de una cartera de proyectos de transformación digital:
coste real frente a presupuesto, hitos, semáforo de estado y velocidad de los equipos Scrum.

> Los datos son sintéticos (generados con `python/generar_datos.py`). Clientes, proyectos
> y personas son inventados.

## Flujo

```
generar_datos.py ──► data/*.csv ──► cargar_postgres.py ──► PostgreSQL (esquema cartera)
                                     (valida y carga)         │
                                                              ├─ vw_estado_proyecto
                                                              ├─ vw_velocidad_sprint
                                                              └─ vw_coste_mensual ──► Power BI
```

| Paso | Archivo | Qué hace |
|---|---|---|
| 1 | `python/generar_datos.py` | Genera 5 CSV: clientes, proyectos, hitos, sprints e imputaciones (~256k filas) |
| 2 | `sql/01_esquema.sql` | Crea las tablas con claves, restricciones `CHECK` e índices |
| 3 | `python/cargar_postgres.py` | Valida los CSV (duplicados, huérfanos, rangos) y los carga con `COPY` en una sola transacción |
| 4 | `sql/02_vistas_kpi.sql` | Vistas con la lógica de KPIs: desviación de coste, semáforo, velocidad con media móvil |
| 5 | `sql/03_optimizacion.sql` | Prueba de rendimiento con `EXPLAIN ANALYZE`, antes y después de un índice compuesto |

## Cómo ejecutarlo

```bash
python python/generar_datos.py
createdb -U postgres cartera
psql -U postgres -d cartera -f sql/01_esquema.sql
pip install "psycopg[binary]"
set PGPASSWORD=tu_contraseña
python python/cargar_postgres.py
psql -U postgres -d cartera -f sql/02_vistas_kpi.sql
psql -U postgres -d cartera -f sql/03_optimizacion.sql
```

En Power BI Desktop: *Obtener datos → Base de datos PostgreSQL* → servidor `localhost`,
base de datos `cartera` → seleccionar las tres vistas `vw_*`.

## Reglas del semáforo

| Estado | Condición |
|---|---|
| Rojo | Coste real > 110 % del presupuesto, o 2+ hitos vencidos sin cerrar |
| Ámbar | Coste real > 100 % del presupuesto, o 2+ hitos entregados con más de 7 días de retraso |
| Verde | Resto |
