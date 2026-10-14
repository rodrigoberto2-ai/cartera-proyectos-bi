-- Usuario de solo lectura para el asistente de IA.
-- Solo puede leer las tres vistas de KPIs: nada de tablas, nada de escribir.
-- Antes de ejecutarlo, cambia la contraseña.

CREATE ROLE asistente_ro LOGIN PASSWORD 'CAMBIA_ESTA_CONTRASENA';

GRANT CONNECT ON DATABASE cartera TO asistente_ro;
GRANT USAGE ON SCHEMA cartera TO asistente_ro;
GRANT SELECT ON cartera.vw_estado_proyecto,
                cartera.vw_velocidad_sprint,
                cartera.vw_coste_mensual
TO asistente_ro;

-- Por si acaso: toda transacción de este usuario es de solo lectura
-- y ninguna consulta puede durar más de 5 segundos.
ALTER ROLE asistente_ro SET default_transaction_read_only = on;
ALTER ROLE asistente_ro SET statement_timeout = '5s';
