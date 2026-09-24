"""
Genera los CSV sintéticos de la cartera de proyectos (carpeta data/).

Los datos son inventados: clientes, proyectos y personas no existen.
Se usa una semilla fija para que el resultado sea siempre el mismo.

Uso:
    python python/generar_datos.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(2026)

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

HOY = date(2026, 9, 21)

SECTORES = {
    "Transporte": ["Operador Ferroviario Norte", "Aeropuertos del Centro", "Autoridad Portuaria Sur"],
    "Defensa": ["Mando de Sistemas Aéreos", "Centro Logístico de Defensa"],
    "Administración Pública": ["Consejería de Hacienda", "Agencia de Empleo Regional", "Ayuntamiento Metropolitano"],
    "Energía": ["Distribuidora Eléctrica Levante", "Red de Gas Peninsular"],
    "Banca": ["Banco Mediterráneo", "Caja Rural del Duero"],
    "Telecomunicaciones": ["Operador Móvil Ibérico"],
}

TIPOS = [
    ("Migración a cloud", "Scrum"),
    ("Cuadro de mando corporativo", "Scrum"),
    ("Modernización ERP", "Waterfall"),
    ("Portal de servicios digitales", "Scrum"),
    ("Data Lake y gobierno del dato", "Scrum"),
    ("Automatización de procesos (RPA)", "Scrum"),
    ("Renovación de infraestructura", "Waterfall"),
    ("Ciberseguridad y SOC", "Waterfall"),
]

JEFES = ["L. Martín", "C. Ortega", "P. Navarro", "A. Ruiz", "M. Castillo", "J. Herrera"]

PERFILES = {  # perfil: coste/hora
    "Jefe de proyecto": 62,
    "Arquitecto": 58,
    "Analista funcional": 45,
    "Desarrollador": 38,
    "Analista de datos": 40,
    "QA": 34,
}

TAREAS = ["Desarrollo", "Análisis", "Pruebas", "Reuniones", "Documentación", "Soporte"]

HITOS = ["Kick-off", "Análisis cerrado", "Diseño aprobado", "Primera entrega", "Pruebas UAT", "Puesta en producción"]


def escribir(nombre, cabecera, filas):
    with open(DATA / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)
    print(f"{nombre}: {len(filas)} filas")


def main():
    clientes, proyectos, sprints, hitos, imputaciones = [], [], [], [], []

    cid = 0
    for sector, nombres in SECTORES.items():
        for n in nombres:
            cid += 1
            clientes.append([cid, n, sector])

    for pid in range(1, 61):
        cliente = random.choice(clientes)
        tipo, metodologia = random.choice(TIPOS)
        inicio = date(2025, 1, 6) + timedelta(days=random.randint(0, 420))
        duracion = random.choice([120, 180, 240, 300, 365])
        fin_plan = inicio + timedelta(days=duracion)
        presupuesto = round(random.uniform(180, 1400)) * 1000

        # perfil de riesgo del proyecto: condiciona retrasos y sobrecoste
        riesgo = random.choices(["bajo", "medio", "alto"], weights=[5, 3, 2])[0]
        retraso_base = {"bajo": 0, "medio": 12, "alto": 35}[riesgo]
        sobrecoste = {"bajo": 0.90, "medio": 0.96, "alto": 1.05}[riesgo]

        fin_real = None
        if fin_plan + timedelta(days=retraso_base) < HOY:
            fin_real = fin_plan + timedelta(days=retraso_base + random.randint(-5, 15))
            if fin_real > HOY:
                fin_real = None

        proyectos.append([
            pid, f"PRY-{pid:03d}", f"{tipo} - {cliente[1]}", cliente[0], tipo, metodologia,
            random.choice(JEFES), inicio, fin_plan, fin_real or "", presupuesto,
        ])

        # hitos repartidos a lo largo del plan
        for i, h in enumerate(HITOS):
            f_plan = inicio + timedelta(days=int(duracion * i / (len(HITOS) - 1)))
            retraso = max(0, int(random.gauss(retraso_base * (i / len(HITOS)), 6)))
            f_real = f_plan + timedelta(days=retraso)
            hitos.append([len(hitos) + 1, pid, h, f_plan, f_real if f_real <= HOY else ""])

        # sprints de 2 semanas (solo proyectos Scrum)
        if metodologia == "Scrum":
            capacidad = random.randint(28, 45)
            d, n = inicio, 1
            limite = min(fin_real or HOY, HOY)
            while d + timedelta(days=14) <= limite:
                comprometidos = capacidad + random.randint(-4, 6)
                # los equipos mejoran con el tiempo; los de riesgo alto cumplen menos
                eficacia = {"bajo": 0.92, "medio": 0.84, "alto": 0.72}[riesgo] + min(n, 10) * 0.008
                completados = min(comprometidos, max(0, round(comprometidos * random.gauss(eficacia, 0.07))))
                sprints.append([len(sprints) + 1, pid, n, d, d + timedelta(days=13), comprometidos, completados])
                d += timedelta(days=14)
                n += 1

        # imputaciones diarias de horas (tabla grande, sirve para la prueba de rendimiento)
        coste_obj = presupuesto * sobrecoste
        dias_lab = [inicio + timedelta(days=k) for k in range((min(fin_real or HOY, HOY) - inicio).days + 1)]
        dias_lab = [x for x in dias_lab if x.weekday() < 5]
        if not dias_lab:
            continue
        coste_dia = coste_obj / ((fin_plan - inicio).days * 5 / 7)
        # tamaño de equipo según presupuesto diario (~7 h/persona a una tarifa media de 45 EUR)
        n_equipo = max(3, round(coste_dia / (45 * 7)))
        equipo = [(f"EMP-{pid:02d}{k:02d}", random.choice(list(PERFILES))) for k in range(n_equipo)]
        tarifa_equipo = sum(PERFILES[p] for _, p in equipo)
        horas_persona = coste_dia / tarifa_equipo
        for dia in dias_lab:
            for empleado, perfil in equipo:
                h_dia = horas_persona * random.uniform(0.75, 1.25)
                # cada persona reparte su jornada en 1-3 tareas
                tareas = random.sample(TAREAS, k=random.randint(1, 3))
                for tarea in tareas:
                    horas = round(h_dia / len(tareas), 1)
                    if horas <= 0:
                        continue
                    imputaciones.append([len(imputaciones) + 1, pid, empleado, dia, perfil, tarea,
                                         horas, round(horas * PERFILES[perfil], 2)])

    escribir("clientes.csv", ["cliente_id", "nombre", "sector"], clientes)
    escribir("proyectos.csv", ["proyecto_id", "codigo", "nombre", "cliente_id", "tipo", "metodologia",
                               "jefe_proyecto", "fecha_inicio", "fecha_fin_plan", "fecha_fin_real", "presupuesto"], proyectos)
    escribir("hitos.csv", ["hito_id", "proyecto_id", "hito", "fecha_plan", "fecha_real"], hitos)
    escribir("sprints.csv", ["sprint_id", "proyecto_id", "numero", "fecha_inicio", "fecha_fin",
                             "puntos_comprometidos", "puntos_completados"], sprints)
    escribir("imputaciones.csv", ["imputacion_id", "proyecto_id", "empleado", "fecha", "perfil", "tarea",
                                  "horas", "coste"], imputaciones)


if __name__ == "__main__":
    main()
