"""
Asistente de IA sobre la cartera de proyectos.

El usuario pregunta en lenguaje natural, Claude genera la consulta SQL sobre
las vistas de KPIs, la consulta se ejecuta en PostgreSQL con un usuario de
solo lectura y Claude redacta la respuesta con el dato real.

Ejecutar:  streamlit run asistente/app.py
"""
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import anthropic
import pandas as pd
import psycopg
import streamlit as st

CARPETA = Path(__file__).resolve().parent


def cargar_env(ruta: Path) -> None:
    """Lee un .env sencillo (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


cargar_env(CARPETA / ".env")

# "ollama" = modelo local y gratuito (por defecto) · "claude" = API de Anthropic (de pago)
PROVEEDOR = os.getenv("PROVEEDOR", "ollama").lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODELO = os.getenv("OLLAMA_MODELO", "qwen2.5-coder:7b")
MODELO = "claude-opus-5-5"
PRECIO_ENTRADA = 4.00 / 1_000_000   # USD por token de entrada
PRECIO_SALIDA = 20.00 / 1_000_000   # USD por token de salida (incluye razonamiento)
MAX_FILAS = 200
REGISTRO = CARPETA / "registro_preguntas.csv"

CONEXION = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "cartera"),
    user=os.getenv("PG_ASISTENTE_USER", "asistente_ro"),
    password=os.getenv("PG_ASISTENTE_PASSWORD"),
)

VISTAS = {"vw_estado_proyecto", "vw_velocidad_sprint", "vw_coste_mensual"}

# Base de datos: PostgreSQL en local; en la nube, una copia de las vistas en DuckDB
# (python asistente/exportar_duckdb.py), que entiende el mismo SQL y viaja con el código.
DUCKDB_RUTA = CARPETA / "datos_cartera.duckdb"
BD = os.getenv("BD", "postgres" if os.getenv("PG_ASISTENTE_PASSWORD") else "duckdb").lower()
MAX_PREGUNTAS = int(os.getenv("MAX_PREGUNTAS", "15"))  # por visitante, para no agotar la cuota gratuita

ESQUEMA = """
Base de datos PostgreSQL, esquema `cartera`. Solo puedes consultar estas tres vistas:

1. cartera.vw_estado_proyecto: una fila por proyecto (60 proyectos de TI).
   proyecto_id, codigo (ej. 'PRY-001'), nombre, cliente, sector, tipo,
   metodologia ('Scrum' o 'Waterfall'), jefe_proyecto, fecha_inicio, fecha_fin_plan,
   fecha_fin_real (NULL si sigue en curso), situacion ('En curso' o 'Cerrado'),
   presupuesto (EUR), coste_real (EUR), desviacion_coste (proporción: 0.12 = 12 % por encima),
   hitos_total, hitos_cumplidos, hitos_con_retraso, hitos_vencidos,
   semaforo ('Rojo', 'Ámbar' o 'Verde').

2. cartera.vw_velocidad_sprint: una fila por sprint (solo proyectos Scrum).
   proyecto_id, codigo, numero (número del sprint), fecha_inicio, fecha_fin,
   puntos_comprometidos, puntos_completados, cumplimiento (proporción),
   velocidad_media_3 (media de puntos completados de los 3 últimos sprints).

3. cartera.vw_coste_mensual: horas y coste por proyecto, mes y perfil.
   proyecto_id, mes (primer día del mes), perfil, horas, coste (EUR).

Reglas de negocio:
- La desviación de varios proyectos juntos se calcula como SUM(coste_real) / SUM(presupuesto) - 1,
  nunca como media de desviacion_coste.
- Para unir proyectos con su coste mensual usa proyecto_id.
"""

INSTRUCCIONES_SQL = f"""Eres un analista de datos que traduce preguntas en español a SQL de PostgreSQL.
{ESQUEMA}
Escribe UNA sola consulta SELECT (puede empezar con WITH) que responda a la pregunta.
Usa siempre el esquema cartera y solo las tres vistas. Nunca modifiques datos.
Incluye siempre en el SELECT los valores numéricos que justifican la respuesta, con un alias claro
(por ejemplo, si preguntan qué sector tiene más sobrecoste, devuelve el sector y su desviación calculada).
Si la pregunta no se puede responder con estos datos, deja "sql" vacío y explica por qué en "explicacion"."""

INSTRUCCIONES_RESPUESTA = """Eres el asistente de datos de un director de proyectos.
Responde en español, en dos o tres frases, usando solo los números del resultado que te paso.
Formatea los importes en euros con separador de miles y los porcentajes con un decimal.
Si el resultado está vacío, dilo con claridad. No inventes datos.
Usa nombres naturales para las columnas: velocidad_media_3 es "la velocidad media de los últimos 3 sprints",
desviacion_coste es "la desviación sobre el presupuesto"."""

ESQUEMA_SALIDA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "explicacion": {"type": "string"},
    },
    "required": ["sql", "explicacion"],
    "additionalProperties": False,
}

PALABRAS_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|merge|call|do|vacuum|execute)\b",
    re.IGNORECASE,
)


@st.cache_resource
def cliente_claude() -> anthropic.Anthropic:
    return anthropic.Anthropic()


class Uso:
    def __init__(self, entrada: int, salida: int):
        self.input_tokens, self.output_tokens = entrada, salida


def llamar_ollama(system: str, mensaje: str, formato: dict | None = None):
    """Una llamada al modelo local de Ollama (gratis, los datos no salen del equipo)."""
    import urllib.request
    cuerpo = {
        "model": OLLAMA_MODELO,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": mensaje}],
    }
    if formato:
        cuerpo["format"] = formato
    peticion = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=300) as r:
        datos = json.loads(r.read().decode("utf-8"))
    uso = Uso(datos.get("prompt_eval_count", 0), datos.get("eval_count", 0))
    return datos["message"]["content"], uso


GEMINI_MODELOS = [m.strip() for m in os.getenv(
    "GEMINI_MODELOS",
    "gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-latest,gemini-3.8-flash",
).split(",") if m.strip()]


def llamar_gemini(system: str, mensaje: str, formato: dict | None = None):
    """Gemini por su API REST (plan gratuito). Prueba los modelos de la lista en orden."""
    import urllib.error
    import urllib.request
    clave = os.getenv("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta GEMINI_API_KEY en asistente/.env.")
    config = {"temperature": 0}
    if formato:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = formato
    cuerpo = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": mensaje}]}],
        "generationConfig": config,
    }).encode("utf-8")
    ultimo_error = None
    for modelo in GEMINI_MODELOS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        peticion = urllib.request.Request(url, data=cuerpo, headers={
            "Content-Type": "application/json", "x-goog-api-key": clave})
        try:
            with urllib.request.urlopen(peticion, timeout=30) as r:
                datos = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            ultimo_error = f"{modelo}: {e.code} {e.read().decode('utf-8', 'ignore')[:200]}"
            if e.code in (400, 403, 404, 429) or e.code >= 500:
                continue  # no disponible, sin cuota o saturado: probar el siguiente modelo
            raise RuntimeError(ultimo_error)
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo_error = f"{modelo}: {e}"
            continue
        partes = datos["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes)
        meta = datos.get("usageMetadata", {})
        st.session_state["modelo_usado"] = modelo
        return texto, Uso(meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0))
    raise RuntimeError(f"Ningún modelo de Gemini respondió. Último error: {ultimo_error}")


def llamar_ia(system: str, mensaje: str, formato: dict | None = None):
    if PROVEEDOR == "claude":
        return llamar_claude(system, mensaje, formato)
    if PROVEEDOR == "gemini":
        return llamar_gemini(system, mensaje, formato)
    return llamar_ollama(system, mensaje, formato)


def llamar_claude(system: str, mensaje: str, formato: dict | None = None):
    """Una llamada a Claude con fallback de servidor ante una negativa."""
    output_config = {"effort": "low"}
    if formato:
        output_config["format"] = {"type": "json_schema", "schema": formato}
    respuesta = cliente_claude().beta.messages.create(
        model=MODELO,
        max_tokens=8000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config=output_config,
        messages=[{"role": "user", "content": mensaje}],
    )
    if respuesta.stop_reason == "refusal":
        raise RuntimeError("El modelo no ha podido responder a esta pregunta.")
    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    return texto, respuesta.usage


def validar_sql(sql: str) -> str:
    """Solo una consulta de lectura, solo sobre las vistas permitidas."""
    limpio = sql.strip().rstrip(";").strip()
    if ";" in limpio:
        raise ValueError("Solo se permite una consulta.")
    if not re.match(r"^(select|with)\b", limpio, re.IGNORECASE):
        raise ValueError("La consulta tiene que empezar por SELECT o WITH.")
    if PALABRAS_PROHIBIDAS.search(limpio):
        raise ValueError("La consulta contiene una operación que no es de lectura.")
    referencias = re.findall(r"\b(?:from|join)\s+([a-z_][\w.]*)", limpio, re.IGNORECASE)
    ctes = {c.lower() for c in re.findall(r"\b(\w+)\s+as\s*\(", limpio, re.IGNORECASE)}
    for ref in referencias:
        nombre = ref.lower().split(".")[-1]
        if nombre not in VISTAS and nombre not in ctes:
            raise ValueError(f"La consulta usa '{ref}', que no está permitido.")
    return f"SELECT * FROM ({limpio}) AS t LIMIT {MAX_FILAS}"


def ejecutar(sql: str) -> pd.DataFrame:
    if BD == "duckdb":
        import duckdb
        con = duckdb.connect(str(DUCKDB_RUTA), read_only=True)
        try:
            return con.execute(sql).df()
        finally:
            con.close()
    with psycopg.connect(**CONEXION) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            columnas = [c.name for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columnas)


def registrar(fila: dict) -> None:
    nuevo = not REGISTRO.exists()
    with open(REGISTRO, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fila))
        if nuevo:
            w.writeheader()
        w.writerow(fila)


def responder(pregunta: str) -> dict:
    inicio = time.time()
    texto, uso1 = llamar_ia(INSTRUCCIONES_SQL, pregunta, ESQUEMA_SALIDA)
    plan = json.loads(texto)
    resultado = {"pregunta": pregunta, "sql": plan["sql"], "explicacion": plan["explicacion"]}

    tokens_in, tokens_out = uso1.input_tokens, uso1.output_tokens
    if plan["sql"].strip():
        sql_seguro = validar_sql(plan["sql"])
        df = ejecutar(sql_seguro)
        datos = df.head(50).to_csv(index=False)
        texto2, uso2 = llamar_ia(
            INSTRUCCIONES_RESPUESTA,
            f"Pregunta: {pregunta}\n\nResultado de la consulta (CSV):\n{datos}",
        )
        tokens_in += uso2.input_tokens
        tokens_out += uso2.output_tokens
        resultado.update(respuesta=texto2, datos=df)
    else:
        resultado.update(respuesta=plan["explicacion"], datos=None)

    coste = tokens_in * PRECIO_ENTRADA + tokens_out * PRECIO_SALIDA if PROVEEDOR == "claude" else 0.0
    resultado.update(tokens_in=tokens_in, tokens_out=tokens_out, coste=coste,
                     segundos=time.time() - inicio)
    registrar({
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "pregunta": pregunta, "sql": plan["sql"],
        "tokens_entrada": tokens_in, "tokens_salida": tokens_out,
        "coste_usd": round(coste, 5),
    })
    return resultado


# ------------------------------------------------------------------ interfaz
# Portal: el cuadro de mando de Power BI a la izquierda y el asistente de IA a la derecha,
# con la misma paleta que el informe (verde petróleo, degradado de las tarjetas y fondo gris azulado).
import streamlit.components.v1 as components

POWERBI_URL = os.getenv(
    "POWERBI_URL",
    "https://app.powerbi.com/view?r=eyJrIjoiN2JkZTZhN2MtZmRmZC00Y2M0LWFlNGUtNjg4ODlkOWM5N2QyIiwidCI6ImFiMTUzNmU4LWVkYzgtNDE4OC1iM2U3LWNkMjU3MDZiODdlMCJ9&pageName=a12dc0d2106a6ab753ed",
)
ALTO = 600  # informe y asistente comparten la misma altura

st.set_page_config(page_title="Portal · Cartera de Proyectos", page_icon="📊", layout="wide")
st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  :root {{
    --teal: #155E66; --teal-2: #1E6F78; --teal-soft: #8DB9BD;
    --fondo: #EEF4F6; --tinta: #163A40; --tinta-suave: #5B7479; --linea: #D6E4E7;
  }}
  html, body, .stApp, .stApp p, .stApp button, .stApp textarea, .stApp summary {{ font-family: 'Inter', sans-serif; }}
  .stApp {{ background: var(--fondo); }}
  header[data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding: 1.1rem 1.6rem 0.6rem; max-width: 100%; }}

  /* barra de título, como la cabecera del informe */
  .barra {{ background: var(--teal); color: #fff; border-radius: 18px; padding: 16px 24px;
           display: flex; justify-content: space-between; align-items: center; gap: 12px;
           margin-bottom: 14px; box-shadow: 0 6px 18px rgba(21,94,102,.18); }}
  .barra b {{ letter-spacing: .2em; font-weight: 600; font-size: 17px; }}
  .barra span {{ font-size: 12px; letter-spacing: .06em; opacity: .85; text-align: right; }}

  /* informe: tarjeta blanca redondeada */
  [data-testid="stIFrame"], iframe[title="st.iframe"] {{ border-radius: 18px; background: #fff;
           box-shadow: 0 8px 24px rgba(21,94,102,.12); }}

  /* panel del asistente: misma altura que el informe */
  .stApp .st-key-panel {{ height: {ALTO}px !important; max-height: {ALTO}px; flex: 0 0 auto !important; background: #fff; border-radius: 18px; overflow: hidden;
           box-shadow: 0 8px 24px rgba(21,94,102,.12); gap: 0 !important; }}
  .st-key-cabecera {{ background: linear-gradient(135deg, var(--teal) 0%, var(--teal-2) 45%, var(--teal-soft) 100%);
           padding: 16px 16px 14px; gap: 10px !important; }}
  .cab-titulo {{ color: #fff; font-weight: 600; letter-spacing: .14em; font-size: 13px; }}
  .cab-sub {{ color: rgba(255,255,255,.82); font-size: 11.5px; margin-top: 2px; }}

  /* preguntas de ejemplo: píldoras de cristal (liquid glass) */
  .st-key-chips {{ flex-direction: row !important; flex-wrap: wrap; gap: 6px !important; }}
  .st-key-chips [data-testid="stElementContainer"] {{ width: auto !important; }}
  .st-key-chips button {{
      background: rgba(255,255,255,.16) !important; color: #fff !important;
      border: 1px solid rgba(255,255,255,.45) !important; border-radius: 999px !important;
      padding: 3px 12px !important; min-height: 0 !important;
      backdrop-filter: blur(12px) saturate(160%); -webkit-backdrop-filter: blur(12px) saturate(160%);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.55), inset 0 -1px 0 rgba(255,255,255,.12),
                  0 4px 14px rgba(9,40,44,.18);
      transition: background .2s, transform .15s; }}
  .st-key-chips button:hover {{ background: rgba(255,255,255,.30) !important; transform: translateY(-1px); }}
  .st-key-chips button p {{ font-size: 12px !important; font-weight: 500; }}

  /* conversación: ocupa el espacio que queda y hace scroll */
  .st-key-panel > div:has(.st-key-conv) {{ flex: 1 1 auto !important; min-height: 0; overflow-y: auto;
           display: flex; flex-direction: column-reverse; }}  /* el scroll empieza abajo, en la última respuesta */
  .st-key-panel > div:has(.st-key-entrada) {{ order: 3; }}
  .st-key-conv {{ padding: 12px 14px 4px; gap: 10px !important; }}
  .vacio {{ color: var(--tinta-suave); font-size: 13px; line-height: 1.5; padding: 6px 2px; }}
  [data-testid="stChatMessage"] {{ background: #F3F8F9; border-radius: 14px; padding: 10px 12px; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ background: var(--teal); }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p {{ color: #fff; }}
  [data-testid="stChatMessage"] p {{ font-size: 13.5px; color: var(--tinta); }}
  [data-testid="stChatMessageAvatarAssistant"] {{ background: var(--teal-2); }}
  .meta {{ color: var(--tinta-suave); font-size: 11px; }}
  [data-testid="stExpander"] details {{ border-radius: 10px; border-color: var(--linea); }}
  [data-testid="stExpander"] summary p {{ font-size: 12px; color: var(--teal); }}

  /* caja de texto abajo */
  .st-key-entrada {{ padding: 8px 12px 12px; border-top: 1px solid var(--linea); }}
  .st-key-entrada [data-testid="stChatInput"] > div {{ border-radius: 999px; border: 1px solid var(--linea);
           background: #fff; }}
  .st-key-entrada [data-testid="stChatInputSubmitButton"] {{ background: var(--teal); color: #fff; border-radius: 999px; }}
</style>
""", unsafe_allow_html=True)

MOTOR = {
    "claude": f"Claude ({MODELO})",
    "gemini": "Gemini",
}.get(PROVEEDOR, f"modelo local {OLLAMA_MODELO}")
ORIGEN = "PostgreSQL · solo lectura" if BD == "postgres" else "copia de las vistas · solo lectura"

st.markdown(
    '<div class="barra"><b>CARTERA DE PROYECTOS</b>'
    '<span>Cuadro de mando en Power BI · asistente de IA sobre los mismos datos</span></div>',
    unsafe_allow_html=True,
)

EJEMPLOS = {
    "Semáforo": "¿Cuántos proyectos hay en rojo, ámbar y verde?",
    "Top desviaciones": "¿Qué 5 proyectos se desvían más del presupuesto?",
    "Sobrecoste por sector": "¿Qué sector tiene más sobrecoste en los proyectos cerrados?",
    "Coste de junio": "¿Cuál fue el coste total en junio de 2026?",
    "Velocidad PRY-001": "¿Cómo va la velocidad de los últimos sprints del PRY-001?",
}

if "historial" not in st.session_state:
    st.session_state.historial = []
st.session_state.setdefault("preguntas_hechas", 0)

col_bi, col_ia = st.columns([7, 3], gap="medium")

with col_bi:
    components.iframe(POWERBI_URL, height=ALTO, scrolling=False)

with col_ia:
    with st.container(key="panel"):
        pregunta = None
        with st.container(key="cabecera"):
            st.markdown(
                f'<div class="cab-titulo">PREGUNTA A LOS DATOS</div>'
                f'<div class="cab-sub">IA: {MOTOR} · {ORIGEN}</div>',
                unsafe_allow_html=True,
            )
            with st.container(key="chips"):
                for i, (etiqueta, texto) in enumerate(EJEMPLOS.items()):
                    if st.button(etiqueta, key=f"chip_{i}"):
                        pregunta = texto

        with st.container(key="entrada"):
            escrita = st.chat_input("Escribe tu pregunta…")
        pregunta = escrita or pregunta

        if pregunta and st.session_state.preguntas_hechas >= MAX_PREGUNTAS:
            st.toast(f"Has llegado al límite de {MAX_PREGUNTAS} preguntas de esta demo. ¡Gracias por probarla!")
            pregunta = None
        aviso = None
        if pregunta:
            st.session_state.preguntas_hechas += 1
            with st.spinner("Consultando los datos…"):
                try:
                    st.session_state.historial.insert(0, responder(pregunta))
                except anthropic.AuthenticationError:
                    aviso = "La clave de la API de Claude no es válida. Revisa ANTHROPIC_API_KEY."
                except anthropic.RateLimitError:
                    aviso = "Demasiadas peticiones seguidas. Espera unos segundos y vuelve a preguntar."
                except anthropic.APIConnectionError:
                    aviso = "No hay conexión con la API de Claude."
                except anthropic.APIStatusError as e:
                    aviso = f"Error de la API de Claude ({e.status_code}): {e.message}"
                except psycopg.OperationalError:
                    aviso = "No se puede conectar a PostgreSQL. Revisa el servidor y el usuario de lectura en el .env."
                except OSError as e:
                    aviso = f"No hay conexión con el modelo de IA. ({e})"
                except (ValueError, RuntimeError, psycopg.Error, json.JSONDecodeError) as e:
                    aviso = f"No he podido responder: {e}"

        with st.container(key="conv"):
            if aviso:
                st.warning(aviso)
            if not st.session_state.historial:
                st.markdown('<div class="vacio">Pregunta lo que quieras sobre la cartera o pulsa uno de los '
                            'ejemplos de arriba. La respuesta sale de la base de datos y verás cómo se ha '
                            'calculado.</div>', unsafe_allow_html=True)
            for r in reversed(st.session_state.historial):  # la más reciente abajo, junto a la caja
                with st.chat_message("user"):
                    st.write(r["pregunta"])
                with st.chat_message("assistant"):
                    st.write(r["respuesta"])
                    if r.get("datos") is not None and not r["datos"].empty:
                        with st.expander("Ver datos"):
                            st.dataframe(r["datos"], use_container_width=True, hide_index=True)
                    with st.expander("Cómo lo he calculado"):
                        st.code(r["sql"] or "-- sin consulta", language="sql")
                        st.caption(r["explicacion"])
                    coste_txt = {"claude": f"≈ {r['coste']:.4f} USD", "gemini": "plan gratuito"}.get(
                        PROVEEDOR, "coste 0 (modelo local)")
                    st.markdown(f'<div class="meta">{r["tokens_in"]:,} + {r["tokens_out"]:,} tokens · '
                                f'{coste_txt} · {r["segundos"]:.1f} s</div>', unsafe_allow_html=True)
