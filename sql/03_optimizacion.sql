-- Prueba de rendimiento: coste de un proyecto en un trimestre.
-- Es la consulta que lanza el informe cada vez que alguien filtra un proyecto.
--
-- En pgAdmin: seleccionar cada bloque con el ratón y ejecutarlo por separado (F5).
-- VACUUM no puede ir en la misma ejecución que el resto (no admite transacciones).

-- Bloque 1: consulta SIN índice ------------------------------------------------
DROP INDEX IF EXISTS cartera.ix_imputaciones_proyecto_fecha;
ANALYZE cartera.imputaciones;

EXPLAIN (ANALYZE, BUFFERS)
SELECT perfil, SUM(horas) AS horas, SUM(coste) AS coste
FROM cartera.imputaciones
WHERE proyecto_id = 13
  AND fecha BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'
GROUP BY perfil;


-- Bloque 2: crear el índice ----------------------------------------------------
-- Índice compuesto: primero la columna de igualdad (proyecto_id) y después la de rango (fecha).
-- INCLUDE añade las columnas que se suman para que PostgreSQL no tenga que ir a la tabla
-- (index-only scan).
CREATE INDEX ix_imputaciones_proyecto_fecha
    ON cartera.imputaciones (proyecto_id, fecha)
    INCLUDE (perfil, horas, coste);


-- Bloque 3: ejecutar SOLO esta línea --------------------------------------------
-- Actualiza estadísticas y el visibility map (necesario para el index-only scan).
VACUUM ANALYZE cartera.imputaciones;


-- Bloque 4: la misma consulta CON índice ---------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT perfil, SUM(horas) AS horas, SUM(coste) AS coste
FROM cartera.imputaciones
WHERE proyecto_id = 13
  AND fecha BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'
GROUP BY perfil;
