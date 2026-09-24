-- Modelo relacional de la cartera de proyectos (PostgreSQL)
-- Ejecutar conectado a la base de datos "cartera":
--   psql -U postgres -d cartera -f sql/01_esquema.sql

DROP SCHEMA IF EXISTS cartera CASCADE;
CREATE SCHEMA cartera;
SET search_path TO cartera;

CREATE TABLE clientes (
    cliente_id   INT PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL UNIQUE,
    sector       VARCHAR(40)  NOT NULL
);

CREATE TABLE proyectos (
    proyecto_id     INT PRIMARY KEY,
    codigo          VARCHAR(10)  NOT NULL UNIQUE,
    nombre          VARCHAR(150) NOT NULL,
    cliente_id      INT NOT NULL REFERENCES clientes (cliente_id),
    tipo            VARCHAR(60)  NOT NULL,
    metodologia     VARCHAR(20)  NOT NULL CHECK (metodologia IN ('Scrum', 'Waterfall')),
    jefe_proyecto   VARCHAR(60)  NOT NULL,
    fecha_inicio    DATE NOT NULL,
    fecha_fin_plan  DATE NOT NULL,
    fecha_fin_real  DATE,
    presupuesto     NUMERIC(12,2) NOT NULL CHECK (presupuesto > 0),
    CHECK (fecha_fin_plan > fecha_inicio)
);

CREATE TABLE hitos (
    hito_id      INT PRIMARY KEY,
    proyecto_id  INT NOT NULL REFERENCES proyectos (proyecto_id),
    hito         VARCHAR(60) NOT NULL,
    fecha_plan   DATE NOT NULL,
    fecha_real   DATE             -- NULL = hito pendiente
);

CREATE TABLE sprints (
    sprint_id             INT PRIMARY KEY,
    proyecto_id           INT NOT NULL REFERENCES proyectos (proyecto_id),
    numero                INT NOT NULL,
    fecha_inicio          DATE NOT NULL,
    fecha_fin             DATE NOT NULL,
    puntos_comprometidos  INT NOT NULL CHECK (puntos_comprometidos >= 0),
    puntos_completados    INT NOT NULL CHECK (puntos_completados >= 0),
    UNIQUE (proyecto_id, numero),
    CHECK (puntos_completados <= puntos_comprometidos)
);

-- Tabla grande (~250k filas): horas imputadas por persona, día y tarea
CREATE TABLE imputaciones (
    imputacion_id  BIGINT PRIMARY KEY,
    proyecto_id    INT NOT NULL REFERENCES proyectos (proyecto_id),
    empleado       VARCHAR(10) NOT NULL,
    fecha          DATE NOT NULL,
    perfil         VARCHAR(40) NOT NULL,
    tarea          VARCHAR(40) NOT NULL,
    horas          NUMERIC(4,1) NOT NULL CHECK (horas > 0 AND horas <= 12),
    coste          NUMERIC(10,2) NOT NULL CHECK (coste >= 0)
);

-- Índices para las claves foráneas más consultadas.
-- El índice de imputaciones por (proyecto_id, fecha) se crea aparte en 03_optimizacion.sql
-- para poder medir el antes y el después.
CREATE INDEX ix_proyectos_cliente ON proyectos (cliente_id);
CREATE INDEX ix_hitos_proyecto    ON hitos (proyecto_id);
CREATE INDEX ix_sprints_proyecto  ON sprints (proyecto_id);
