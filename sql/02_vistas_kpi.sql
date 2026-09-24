-- Vistas que consume Power BI. La lógica de negocio vive aquí y no en DAX,
-- así el mismo KPI da el mismo número en cualquier informe que lo use.

SET search_path TO cartera;

-- 1. Estado de cada proyecto: coste real vs presupuesto, hitos y semáforo
CREATE OR REPLACE VIEW vw_estado_proyecto AS
WITH coste AS (
    SELECT proyecto_id, SUM(coste) AS coste_real, SUM(horas) AS horas_reales
    FROM imputaciones
    GROUP BY proyecto_id
),
h AS (
    SELECT proyecto_id,
           COUNT(*)                                                   AS hitos_total,
           COUNT(fecha_real)                                          AS hitos_cumplidos,
           COUNT(*) FILTER (WHERE fecha_real > fecha_plan + 7)        AS hitos_con_retraso,  -- tolerancia: 1 semana
           COUNT(*) FILTER (WHERE fecha_real IS NULL
                              AND fecha_plan < DATE '2026-09-21')     AS hitos_vencidos
    FROM hitos
    GROUP BY proyecto_id
)
SELECT p.proyecto_id,
       p.codigo,
       p.nombre,
       c.nombre   AS cliente,
       c.sector,
       p.tipo,
       p.metodologia,
       p.jefe_proyecto,
       p.fecha_inicio,
       p.fecha_fin_plan,
       p.fecha_fin_real,
       CASE WHEN p.fecha_fin_real IS NULL THEN 'En curso' ELSE 'Cerrado' END AS situacion,
       p.presupuesto,
       COALESCE(co.coste_real, 0)                                     AS coste_real,
       ROUND(COALESCE(co.coste_real, 0) / p.presupuesto - 1, 4)       AS desviacion_coste,
       h.hitos_total,
       h.hitos_cumplidos,
       h.hitos_con_retraso,
       h.hitos_vencidos,
       CASE
           WHEN COALESCE(co.coste_real, 0) / p.presupuesto > 1.10 OR h.hitos_vencidos >= 2 THEN 'Rojo'
           WHEN COALESCE(co.coste_real, 0) / p.presupuesto > 1.00 OR h.hitos_con_retraso >= 2 THEN 'Ámbar'
           ELSE 'Verde'
       END AS semaforo
FROM proyectos p
JOIN clientes c ON c.cliente_id = p.cliente_id
LEFT JOIN coste co ON co.proyecto_id = p.proyecto_id
LEFT JOIN h        ON h.proyecto_id  = p.proyecto_id;


-- 2. Velocidad por sprint con media móvil de 3 sprints (proyectos Scrum)
CREATE OR REPLACE VIEW vw_velocidad_sprint AS
SELECT s.proyecto_id,
       p.codigo,
       s.numero,
       s.fecha_inicio,
       s.fecha_fin,
       s.puntos_comprometidos,
       s.puntos_completados,
       ROUND(s.puntos_completados::NUMERIC / NULLIF(s.puntos_comprometidos, 0), 3) AS cumplimiento,
       ROUND(AVG(s.puntos_completados) OVER (
             PARTITION BY s.proyecto_id ORDER BY s.numero
             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1)                         AS velocidad_media_3
FROM sprints s
JOIN proyectos p ON p.proyecto_id = s.proyecto_id;


-- 3. Coste mensual por proyecto y perfil (base para el gráfico de consumo acumulado)
CREATE OR REPLACE VIEW vw_coste_mensual AS
SELECT proyecto_id,
       DATE_TRUNC('month', fecha)::DATE AS mes,
       perfil,
       SUM(horas) AS horas,
       SUM(coste) AS coste
FROM imputaciones
GROUP BY proyecto_id, DATE_TRUNC('month', fecha), perfil;
