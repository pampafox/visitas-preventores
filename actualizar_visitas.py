"""
Lee las visitas de la Web de Preventores (Provincia ART) y manda por e-mail
los CSV que usa el tablero "Visitas prioritarias 2026".

Corre en GitHub Actions. Las credenciales llegan por variables de entorno
(secretos del repositorio), nunca escritas en el código:
  PREV_USUARIO, PREV_CLAVE        usuario y contraseña de la Web de Preventores
  GMAIL_USUARIO, GMAIL_CLAVE_APP  cuenta de Gmail que envía y su contraseña de aplicación
  MAIL_PARA                       a quién se manda (por defecto, la misma cuenta de Gmail)
  TELEGRAM_TOKEN, TELEGRAM_CHAT   opcional: token del bot y número del grupo de Telegram
                                  al que se mandan los avisos de vencimiento
  WHATSAPP_DESTINOS               opcional: copia del aviso por WhatsApp con CallMeBot,
                                  un destino por línea con el formato numero:clave
Opcional:
  SOLO_PROBAR=1                   no manda nada, solo muestra el resultado en el registro
"""

import calendar
import csv
import html
import io
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
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

    return del_mes, {
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


# ---------------------------------------------------------------- Telegram

def dd_mm(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso else ""


def esc(texto):
    """Escapa texto para el modo HTML de Telegram."""
    return html.escape(str(texto or ""), quote=False)


def recordatorios(del_mes, ahora):
    """Mismas reglas que el e-mail de vencimientos: antes de las 12 las que vencen
    hoy; después, las que vencen mañana (viernes: sábado a lunes).
    El vencimiento es siempre la Fecha hasta."""
    hoy = ahora.date()
    if ahora.hour < 12:
        fechas, cuando = [hoy], "hoy"
    elif hoy.weekday() == 4:
        fechas, cuando = [hoy + timedelta(days=d) for d in (1, 2, 3)], "entre el sábado y el lunes"
    else:
        fechas, cuando = [hoy + timedelta(days=1)], "mañana"
    buscadas = {f.isoformat() for f in fechas}
    inicio_mes = hoy.replace(day=1).isoformat()
    lista = [f for f in del_mes if f["fecha_hasta"] in buscadas and f["estado"] != "Realizada"]
    lista.sort(key=lambda f: (f["fecha_hasta"], f["empresa"]))
    return lista, cuando, inicio_mes


def mensajes_telegram(lista, cuando, inicio_mes, ahora, limite=3800):
    """Arma el aviso en HTML de Telegram. Si es muy largo lo parte en varios mensajes."""
    n = len(lista)
    titulo = f"⚠️👷 <b>Visitas ART: {n} {'visita que vence' if n == 1 else 'visitas que vencen'} {cuando}</b>"
    pie = f"<i>Datos actualizados: {ahora.strftime('%d/%m/%Y %H:%M')}</i>"
    bloques = []
    for i, f in enumerate(lista, 1):
        empresa = f["empresa"] + (" (otro período)" if f["fecha_desde"] and f["fecha_desde"] < inicio_mes else "")
        bloques.append("\n".join([
            f"{i}. <b>{esc(empresa)}</b>",
            f"{esc(f['tarea'])}",
            f"👤 {esc(f['preventor'])} · {esc(f['estado'])}",
            f"📅 Vence: {dd_mm(f['fecha_hasta'])}",
            f"📍 {esc(f['domicilio'])}, {esc(f['localidad'])}",
        ]))
    mensajes, actual = [], titulo
    for b in bloques:
        if len(actual) + len(b) + 2 > limite:
            mensajes.append(actual)
            actual = b
        else:
            actual += "\n\n" + b
    mensajes.append(actual + "\n\n" + pie)
    return mensajes


def enviar_telegram(token, chat_id, mensajes):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, texto in enumerate(mensajes):
        if i:
            time.sleep(1)
        datos = urllib.parse.urlencode({
            "chat_id": chat_id, "text": texto, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        try:
            with urllib.request.urlopen(url, data=datos, timeout=60) as r:
                respuesta = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                respuesta = json.loads(e.read().decode())
            except Exception:
                respuesta = {"ok": False, "description": str(e)}
        except urllib.error.URLError as e:
            raise SystemExit(f"No se pudo conectar con Telegram: {e.reason}")
        if not respuesta.get("ok"):
            # No se muestra el token: solo la descripción del error de Telegram.
            raise SystemExit("Telegram rechazó el mensaje: " + str(respuesta.get("description", "error desconocido")))
    print(f"Telegram: {len(mensajes)} mensaje(s) enviados al grupo.")


# ---------------------------------------------------------------- WhatsApp (CallMeBot)

def mensaje_whatsapp(lista, cuando, inicio_mes, ahora):
    n = len(lista)
    lineas = [f"⚠️👷 *Visitas ART: {n} {'visita que vence' if n == 1 else 'visitas que vencen'} {cuando}*", ""]
    for i, f in enumerate(lista, 1):
        empresa = f["empresa"] + (" (otro período)" if f["fecha_desde"] and f["fecha_desde"] < inicio_mes else "")
        lineas += [
            f"{i}. *{empresa}*",
            f"{f['tarea']}",
            f"👤 {f['preventor']} · {f['estado']}",
            f"📅 Vence: {dd_mm(f['fecha_hasta'])}",
            f"📍 {f['domicilio']}, {f['localidad']}",
            "",
        ]
    lineas.append(f"_Datos actualizados: {ahora.strftime('%d/%m/%Y %H:%M')}_")
    return "\n".join(lineas)


def destinos_whatsapp(texto):
    """Lee WHATSAPP_DESTINOS. Devuelve (destinos válidos, cantidad de líneas mal escritas).
    Acepta 'numero:clave' con espacios, guiones o + en el número."""
    destinos, malas = [], 0
    for parte in re.split(r"[\n,;]+", texto or ""):
        parte = parte.strip()
        if not parte:
            continue
        numero, sep, clave = parte.partition(":")
        numero = re.sub(r"\D", "", numero)
        clave = re.sub(r"(?i)^\s*(apikey\s*=?)\s*", "", clave).strip()
        if not sep or len(numero) < 10 or not clave:
            malas += 1
            continue
        destinos.append((numero, clave))
    return destinos, malas


def enviar_whatsapp(destinos, texto):
    """Manda el texto con CallMeBot a cada número. Devuelve los finales de los números que fallaron."""
    fallaron = []
    for i, (numero, clave) in enumerate(destinos):
        if i:
            time.sleep(5)  # CallMeBot pide no mandar mensajes seguidos
        url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
            {"phone": numero, "text": texto, "apikey": clave})
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                respuesta = r.read().decode("utf-8", "replace")
            texto_resp = re.sub(r"<[^>]+>", " ", respuesta)
            if re.search(r"error|paused|invalid|not\s+allowed", texto_resp, re.I) and not re.search(r"queued|sent", texto_resp, re.I):
                raise RuntimeError(re.sub(r"\s+", " ", texto_resp).strip()[:200])
            print(f"WhatsApp enviado a ...{numero[-4:]}")
        except Exception as e:
            # No se muestra la clave: solo el final del número y el error.
            print(f"No se pudo mandar el WhatsApp a ...{numero[-4:]}: {e}")
            fallaron.append(numero[-4:])
    return fallaron


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

    del_mes, csvs, cuentas = armar_csvs(asignadas, no_asignadas, hoy)
    print("Resultado:", cuentas)

    tg_token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT", "").strip()
    destinos_wa, wa_malas = destinos_whatsapp(os.environ.get("WHATSAPP_DESTINOS", ""))
    lista, cuando, inicio_mes = recordatorios(del_mes, ahora)
    mensajes = mensajes_telegram(lista, cuando, inicio_mes, ahora) if lista else []
    texto_wa = mensaje_whatsapp(lista, cuando, inicio_mes, ahora) if lista else ""

    if probar:
        for nombre, contenido in csvs.items():
            print(f"\n--- {nombre} ---\n{contenido}")
        print(f"\n--- Telegram ({'configurado' if tg_token and tg_chat else 'sin configurar'}) ---")
        print("\n\n".join(mensajes) if mensajes else f"(no se manda: no hay visitas que venzan {cuando})")
        print(f"\n--- WhatsApp ({len(destinos_wa)} destino(s) válidos, {wa_malas} línea(s) mal escrita(s)) ---")
        print(texto_wa or f"(no se manda: no hay visitas que venzan {cuando})")
        return

    msg = armar_mail(ahora, csvs, cuentas, gmail, destino)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(gmail, gmail_clave)
        s.send_message(msg)
    print(f"E-mail enviado a {destino}.")

    if not lista:
        print(f"Avisos: no hay visitas que venzan {cuando}, no se manda nada.")
        return

    # Cada canal se intenta aunque el otro falle. Si alguno falla, la corrida queda
    # en rojo al final para que GitHub avise (el e-mail de datos ya salió).
    errores = []
    if tg_token and tg_chat:
        try:
            enviar_telegram(tg_token, tg_chat, mensajes)
        except SystemExit as e:
            print(e)
            errores.append(str(e))
    if wa_malas:
        errores.append(f"WHATSAPP_DESTINOS tiene {wa_malas} línea(s) mal escrita(s): el formato es numero:clave, por ejemplo 5492211234567:123456")
    if destinos_wa:
        fallaron = enviar_whatsapp(destinos_wa, texto_wa)
        if fallaron:
            errores.append("No se pudo mandar el WhatsApp a los números terminados en: " + ", ".join(fallaron))
    if errores:
        raise SystemExit(" | ".join(errores))

if __name__ == "__main__":
    sys.exit(main())
