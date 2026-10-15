"""
Lee las visitas de la Web de Preventores (Provincia ART) y manda por e-mail
los CSV que usa el tablero "Visitas prioritarias 2026".

Corre en GitHub Actions. Las credenciales llegan por variables de entorno
(secretos del repositorio), nunca escritas en el código:
  PREV_USUARIO, PREV_CLAVE        usuario y contraseña de la Web de Preventores
  GMAIL_USUARIO, GMAIL_CLAVE_APP  cuenta de Gmail que envía y su contraseña de aplicación
  MAIL_PARA                       a quién se manda (por defecto, la misma cuenta de Gmail)
Opcional:
  SOLO_PROBAR=1                   no manda el e-mail, solo muestra el resultado en el registro
"""

import calendar
import csv
import io
import os
import re
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

WEB = "https://preventores.artprovincia.ar"
API = "https://prod-apigateway.artprovincia.com.ar/hys/preventores/v1/visitas"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
MARCA_ASUNTO = "[datos-visitas]"
POR_PAGINA = 500


# ---------------------------------------------------------------- utilidades

def fecha_iso(texto):
    """'16/10/2026' o '16/10/2026 08:30:00' -> '2026-10-16'. Vacío si no hay."""
    if not texto:
        return ""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(texto))
    if not m:
        return ""
    d, mes, a = m.groups()
    return f"{a}-{int(mes):02d}-{int(d):02d}"


def limpio(valor):
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor).replace("\n", " - ")).strip()


def a_csv(encabezado, filas):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(encabezado)
    for f in filas:
        w.writerow([f.get(c, "") for c in encabezado])
    return buf.getvalue()


# ------------------------------------------------------------------ la web

def iniciar_sesion(page, usuario, clave):
    page.goto(f"{WEB}/login", wait_until="networkidle")
    campo_clave = page.locator('input[type="password"]').first
    campo_clave.wait_for(timeout=30000)
    campo_usuario = page.locator('input[name="username"]')
    if campo_usuario.count() == 0:
        campo_usuario = page.locator(
            'input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'
        )
    campo_usuario.first.fill(usuario)
    campo_clave.fill(clave)

    boton = page.locator('button[type="submit"]')
    if boton.count() == 0:
        boton = page.get_by_role("button", name=re.compile("ingresar|iniciar", re.I))
    boton.first.click()

    try:
        page.wait_for_url(re.compile(r"/(inicio|consultora)"), timeout=45000)
    except PWTimeout:
        if page.get_by_text(re.compile("Error en Credenciales", re.I)).count():
            raise SystemExit("La Web de Preventores rechazó el usuario o la contraseña.")
        raise SystemExit("No se pudo entrar a la Web de Preventores (la página no avanzó después del login).")


def traer_visitas(page, asignadas, fecha_hasta):
    """Devuelve todas las visitas de la pestaña Asignadas o No asignadas,
    sin filtro Desde y con Hasta = fin de mes, llamando a la misma API que usa la web."""
    todas, offset = [], 0
    while True:
        params = {
            "agendadas": "true" if asignadas else "false",
            "realizadas": "false",
            "noAgendadas": "false" if asignadas else "true",
            "prioritarias": "false",
            "compensatoria": "false",
            "emergente": "false",
            "otroPeriodo": "false",
            "fechaHasta": fecha_hasta,
            "calendario": "false",
            "agendaVisitas": "false",
            "codigoPostal": "0",
            "excluirRealizadas": "true",
            "excluirAgendadas": "false" if asignadas else "true",
            "limit": str(POR_PAGINA),
            "offset": str(offset),
        }
        r = page.evaluate(
            """async ([url, params]) => {
                const q = new URLSearchParams(params).toString();
                const r = await fetch(url + '?' + q, {credentials: 'include', headers: {'Cache-Control': 'no-cache'}});
                if (r.status === 204) return {status: 204, visitas: []};
                let j = null; try { j = await r.json(); } catch (e) {}
                return {status: r.status, visitas: (j && j.data && j.data.visitas) || null};
            }""",
            [API, params],
        )
        if r["status"] in (401, 403):
            raise SystemExit("La sesión no quedó iniciada: la API respondió sin autorización.")
        if r["status"] not in (200, 204) or r["visitas"] is None:
            raise SystemExit(f"Respuesta inesperada de la Web de Preventores (código {r['status']}).")
        lote = r["visitas"]
        todas.extend(lote)
        if len(lote) < POR_PAGINA:
            return todas
        offset += POR_PAGINA


# ------------------------------------------------------------- armar CSV

COL_VISITAS = ["id", "empresa", "preventor", "contrato", "establecimiento", "tarea",
               "fecha_desde", "fecha_hasta", "fecha_agendada", "tipo_visita",
               "tipo_establecimiento", "domicilio", "localidad", "provincia", "cp",
               "ultima_visita", "ciiu", "estado"]
COL_VENCIDAS = ["id", "empresa", "preventor", "contrato", "establecimiento", "tarea",
                "fecha_desde", "fecha_hasta", "fecha_agendada", "tipo_visita",
                "domicilio", "localidad", "estado"]
COL_NO_ASIG = ["empresa", "contrato", "establecimiento", "tarea", "fecha_desde",
               "fecha_hasta", "tipo_visita", "localidad", "estado"]


def fila(v):
    return {
        "empresa": limpio(v.get("EM_NOMBRE")),
        "preventor": limpio(v.get("PREVENTORASIGNADO")),
        "contrato": limpio(v.get("VI_CONTRATO")),
        "establecimiento": limpio(v.get("ES_NROESTABLECI")),
        "tarea": limpio(v.get("TAREAS")),
        "fecha_desde": fecha_iso(v.get("VI_FECHADESDE")),
        "fecha_hasta": fecha_iso(v.get("VI_FECHAHASTA")),
        "fecha_agendada": fecha_iso(v.get("FECHA_HORA_INICIO")),
        "tipo_visita": limpio(v.get("TIPOVISITA") or v.get("TV_DESCRIPCION")),
        "tipo_establecimiento": limpio(v.get("TIPOESTABLECIMIENTO")),
        "domicilio": limpio(v.get("DOMICILIO")),
        "localidad": limpio(v.get("ES_LOCALIDAD")),
        "provincia": limpio(v.get("PROVINCIA")),
        "cp": limpio(v.get("ES_CPOSTAL")),
        "ultima_visita": fecha_iso(v.get("ULTVISITAEFECT")),
        "ciiu": limpio(v.get("CIIU")),
        "estado": limpio(v.get("ESTADOVISITA")),
    }


def clave_num(texto):
    return int(texto) if str(texto).isdigit() else 0


def armar_csvs(asignadas, no_asignadas, hoy):
    inicio_mes = hoy.replace(day=1).isoformat()
    fin_mes = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1]).isoformat()

    filas = [fila(v) for v in asignadas]
    del_mes = [f for f in filas if inicio_mes <= f["fecha_hasta"] <= fin_mes]
    vencidas = [f for f in filas if f["fecha_hasta"] and f["fecha_hasta"] < inicio_mes
                and f["estado"] != "Realizada"]

    del_mes.sort(key=lambda f: (f["fecha_hasta"], f["fecha_agendada"] == "",
                                f["fecha_agendada"], f["empresa"], clave_num(f["establecimiento"])))
    for i, f in enumerate(del_mes, 1):
        f["id"] = f"V{i:02d}"

    vencidas.sort(key=lambda f: (f["fecha_hasta"], f["empresa"], clave_num(f["establecimiento"])))
    for i, f in enumerate(vencidas, 1):
        f["id"] = f"A{i:02d}"

    no_asig = [fila(v) for v in no_asignadas]
    no_asig = [f for f in no_asig if inicio_mes <= f["fecha_hasta"] <= fin_mes]
    no_asig.sort(key=lambda f: (f["fecha_hasta"], f["empresa"], clave_num(f["establecimiento"])))

    return {
        "visitas.csv": a_csv(COL_VISITAS, del_mes),
        "vencidas.csv": a_csv(COL_VENCIDAS, vencidas),
        "no_asignadas.csv": a_csv(COL_NO_ASIG, no_asig),
    }, {
        "asignadas_leidas": len(filas),
        "del_mes": len(del_mes),
        "vencidas": len(vencidas),
        "no_asignadas_leidas": len(no_asignadas),
        "no_asignadas_mes": len(no_asig),
    }


# ------------------------------------------------------------------ e-mail

def armar_mail(ahora, csvs, cuentas, remitente, destino):
    hora = ahora.strftime("%d/%m/%Y %H:%M")
    partes = [
        "Datos de la Web de Preventores para el tablero Visitas prioritarias 2026.",
        "Generado automáticamente por GitHub Actions. No responder.",
        "",
        f"corrida: {hora}",
        f"corrida_iso: {ahora.isoformat(timespec='seconds')}",
    ]
    partes += [f"{k}: {v}" for k, v in cuentas.items()]
    for nombre, contenido in csvs.items():
        partes += ["", f"===== INICIO {nombre} =====", contenido.rstrip("\n"), f"===== FIN {nombre} ====="]

    msg = EmailMessage()
    msg["Subject"] = f"{MARCA_ASUNTO} {hora}"
    msg["From"] = remitente
    msg["To"] = destino
    msg.set_content("\n".join(partes) + "\n")
    for nombre, contenido in csvs.items():
        msg.add_attachment(contenido.encode("utf-8"), maintype="text", subtype="csv", filename=nombre)
    return msg


def main():
    usuario = os.environ.get("PREV_USUARIO", "")
    clave = os.environ.get("PREV_CLAVE", "")
    probar = os.environ.get("SOLO_PROBAR") == "1"
    gmail = os.environ.get("GMAIL_USUARIO", "")
    gmail_clave = os.environ.get("GMAIL_CLAVE_APP", "")
    destino = os.environ.get("MAIL_PARA") or gmail

    faltan = [n for n, v in [("PREV_USUARIO", usuario), ("PREV_CLAVE", clave)] if not v]
    if not probar:
        faltan += [n for n, v in [("GMAIL_USUARIO", gmail), ("GMAIL_CLAVE_APP", gmail_clave)] if not v]
    if faltan:
        raise SystemExit("Faltan secretos en el repositorio: " + ", ".join(faltan))

    ahora = datetime.now(TZ).replace(microsecond=0)
    hoy = ahora.date()
    fin_mes = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        page = navegador.new_page(locale="es-AR", timezone_id="America/Argentina/Buenos_Aires")
        try:
            iniciar_sesion(page, usuario, clave)
            page.goto(f"{WEB}/consultora/visitas", wait_until="networkidle")
            hasta = fin_mes.strftime("%d/%m/%Y")
            asignadas = traer_visitas(page, True, hasta)
            no_asignadas = traer_visitas(page, False, hasta)
        except BaseException:
            try:
                page.screenshot(path="error.png", full_page=True)
            except Exception:
                pass
            raise
        finally:
            navegador.close()

    csvs, cuentas = armar_csvs(asignadas, no_asignadas, hoy)
    print("Resultado:", cuentas)

    if probar:
        for nombre, contenido in csvs.items():
            print(f"\n--- {nombre} ---\n{contenido}")
        return

    msg = armar_mail(ahora, csvs, cuentas, gmail, destino)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(gmail, gmail_clave)
        s.send_message(msg)
    print(f"E-mail enviado a {destino}.")


if __name__ == "__main__":
    sys.exit(main())
