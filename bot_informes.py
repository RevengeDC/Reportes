"""
bot_informes.py — Bot Telegram que recibe reportes del grupo y genera minutas con IA Grok
Flujo: mensaje CPNB-ZULIA → extrae fecha/hora + scraping og:image → Grok AI → minuta
"""
import hashlib
import json
import os
import re
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

_DATA        = Path(os.environ.get("DATA_DIR", Path(__file__).parent.resolve()))
MEDIA_DIR    = _DATA / "informes_media"
OFFSET_FILE  = _DATA / "informes_offset.json"
VENEZUELA_TZ = timezone(timedelta(hours=-4))


# ── Configuración ────────────────────────────────────────────────────────────

def _cfg():
    path = Path(__file__).parent / "config.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_bot_token():
    v = os.environ.get("INFORMES_BOT_TOKEN") or _cfg().get("informes_bot_token", "")
    return v.strip()


def get_grok_key():
    v = os.environ.get("GROK_API_KEY") or _cfg().get("grok_api_key", "")
    return v.strip()


# ── Parseo del formato CPNB-ZULIA ────────────────────────────────────────────

def parsear_formato_cpnb(texto):
    """Extrae fecha y hora del formato CPNB-ZULIA si están presentes en el texto."""
    fecha = hora = None
    m = re.search(r'FECHA:\s*(\d{1,2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if m:
        fecha = m.group(1)
    m = re.search(r'HORA:\s*(\d{1,2}:\d{2})', texto, re.IGNORECASE)
    if m:
        hora = m.group(1)
    return fecha, hora


def limpiar_texto_cpnb(texto):
    """Elimina encabezado CPNB-ZULIA, FECHA:, HORA: antes de enviar a la IA."""
    lineas = texto.split('\n')
    resultado = []
    for linea in lineas:
        s = linea.strip()
        if re.match(r'^CPNB[\s\-]*ZULIA$', s, re.IGNORECASE):
            continue
        if re.match(r'^FECHA:\s*\d', s, re.IGNORECASE):
            continue
        if re.match(r'^HORA:\s*\d', s, re.IGNORECASE):
            continue
        resultado.append(linea)
    return '\n'.join(resultado).strip()


# ── Scraping de imagen desde URL de noticia ──────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
}


def extraer_og_image(url):
    """Descarga la og:image / twitter:image del artículo y la guarda en MEDIA_DIR."""
    if not url.startswith("http"):
        return None
    # Links de Telegram no se pueden scrape directamente
    if "t.me" in url or "telegram.me" in url:
        return None
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=15, headers=_HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")

        img_url = None
        for prop, attr in [
            ("property", "og:image"),
            ("name",     "og:image"),
            ("property", "twitter:image"),
            ("name",     "twitter:image"),
        ]:
            tag = soup.find("meta", {prop: attr})
            if tag and tag.get("content"):
                img_url = tag["content"]
                break

        if not img_url:
            return None

        # Convertir a URL absoluta si es relativa
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            from urllib.parse import urlparse
            p = urlparse(url)
            img_url = f"{p.scheme}://{p.netloc}{img_url}"

        ir = requests.get(img_url, timeout=20, headers=_HEADERS)
        ir.raise_for_status()

        ct  = ir.headers.get("content-type", "image/jpeg").lower()
        ext = ".png" if "png" in ct else ".jpg"
        fname = hashlib.md5(img_url.encode()).hexdigest()[:14] + ext
        dest  = MEDIA_DIR / fname
        dest.write_bytes(ir.content)
        print(f"[BOT-INFORMES] Imagen scrapeada: {fname} ← {url[:60]}")
        return dest

    except Exception as e:
        print(f"[BOT-INFORMES] No se pudo obtener imagen de {url}: {e}")
    return None


# ── Telegram helpers ─────────────────────────────────────────────────────────

def tg_get_updates(token, offset=0):
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset, "timeout": 25},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def tg_download_file(token, file_id):
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=10,
    )
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    ext = Path(file_path).suffix or ".jpg"
    raw = requests.get(
        f"https://api.telegram.org/file/bot{token}/{file_path}",
        timeout=60,
    )
    raw.raise_for_status()
    dest = MEDIA_DIR / f"{file_id}{ext}"
    dest.write_bytes(raw.content)
    return dest


# ── Grok AI ──────────────────────────────────────────────────────────────────

def generar_con_ia(texto, media_info=""):
    """Genera Hecho, Análisis y Observación en lenguaje policial venezolano."""
    grok_key = get_grok_key()
    if not grok_key:
        return {"hecho": texto, "analisis": "", "observacion": ""}

    extra  = f"\nMEDIOS ADJUNTOS: {media_info}" if media_info else ""
    prompt = (
        "Eres un analista del CPNB-ZULIA (Cuerpo de Policía Nacional Bolivariana - Zulia), "
        "especializado en monitoreo de redes sociales e inteligencia digital venezolana.\n\n"
        "Basándote en el siguiente reporte de monitoreo cibernético, redacta una minuta policial "
        "profesional en lenguaje formal venezolano:\n\n"
        f"CONTENIDO DEL REPORTE:\n{texto}{extra}\n\n"
        "Responde ÚNICAMENTE con JSON válido (sin texto fuera del JSON):\n"
        "{\n"
        '  "hecho": "descripción factual y objetiva del evento en lenguaje policial formal '
        '(2-4 oraciones, comenzar con \'Mediante patrullaje cibernético...\' o similar)",\n'
        '  "analisis": "análisis del impacto, contexto social/institucional e implicaciones '
        'para el estado Zulia (2-3 oraciones)",\n'
        '  "observacion": "recomendaciones operativas, acciones de seguimiento y alertas '
        'a la superioridad (1-2 oraciones)"\n'
        "}"
    )
    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 700,
            },
            timeout=45,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"[BOT-INFORMES] Error Grok: {e}")
    return {"hecho": texto, "analisis": "", "observacion": ""}


# ── Offset persistence ───────────────────────────────────────────────────────

def _load_offset():
    if OFFSET_FILE.is_file():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def _save_offset(v):
    OFFSET_FILE.write_text(str(v))


# ── Procesamiento de mensajes ────────────────────────────────────────────────

def procesar_mensaje(token, msg):
    from informes import cargar_minutas, guardar_minutas

    texto = msg.get("text") or msg.get("caption") or ""

    # Ignorar mensajes sin contenido relevante
    if not texto and "photo" not in msg and "video" not in msg and "document" not in msg:
        return

    media = []

    # ── Foto directa adjunta al mensaje ──
    if "photo" in msg:
        try:
            p = tg_download_file(token, msg["photo"][-1]["file_id"])
            media.append({"tipo": "foto", "filename": p.name, "path": str(p)})
            print(f"[BOT-INFORMES] Foto descargada: {p.name}")
        except Exception as e:
            print(f"[BOT-INFORMES] Error foto: {e}")

    # ── Video ──
    if "video" in msg:
        try:
            p = tg_download_file(token, msg["video"]["file_id"])
            media.append({"tipo": "video", "filename": p.name, "path": str(p)})
        except Exception as e:
            print(f"[BOT-INFORMES] Error video: {e}")

    # ── Documento / imagen adjunta ──
    if "document" in msg:
        mime = msg["document"].get("mime_type", "")
        if "image" in mime:
            try:
                p = tg_download_file(token, msg["document"]["file_id"])
                media.append({"tipo": "foto", "filename": p.name, "path": str(p)})
            except Exception as e:
                print(f"[BOT-INFORMES] Error documento: {e}")

    # ── Links: guardar + scraping de imagen ──
    all_ents = msg.get("entities", []) + msg.get("caption_entities", [])
    for ent in all_ents:
        url = None
        if ent["type"] == "url":
            url = texto[ent["offset"]: ent["offset"] + ent["length"]]
        elif ent["type"] == "text_link":
            url = ent.get("url", "")
        if not url:
            continue

        media.append({"tipo": "link", "url": url})

        # Intentar obtener imagen del artículo
        img_path = extraer_og_image(url)
        if img_path:
            media.append({
                "tipo":     "foto",
                "filename": img_path.name,
                "path":     str(img_path),
                "fuente":   url,
            })

    # ── Extraer fecha/hora del formato CPNB-ZULIA ──
    fecha_str, hora_str = parsear_formato_cpnb(texto)
    if not fecha_str:
        fecha_str = datetime.now(VENEZUELA_TZ).strftime("%d/%m/%Y")
    if not hora_str:
        hora_str  = datetime.now(VENEZUELA_TZ).strftime("%H:%M")

    # ── Limpiar texto antes de enviar a la IA ──
    contenido = limpiar_texto_cpnb(texto) or "(contenido multimedia)"

    n_fotos  = sum(1 for m in media if m["tipo"] == "foto")
    n_videos = sum(1 for m in media if m["tipo"] == "video")
    n_links  = sum(1 for m in media if m["tipo"] == "link")
    partes   = []
    if n_fotos:  partes.append(f"{n_fotos} foto(s)")
    if n_videos: partes.append(f"{n_videos} video(s)")
    if n_links:  partes.append(f"{n_links} enlace(s)")

    ia = generar_con_ia(contenido, ", ".join(partes))

    minuta = {
        "fecha":          fecha_str,
        "hora":           hora_str,
        "cpnb":           "CPNB-ZULIA",
        "hecho":          ia.get("hecho", contenido),
        "analisis":       ia.get("analisis", ""),
        "observacion":    ia.get("observacion", ""),
        "media":          media,
        "texto_original": texto,
        "ia":             True,
    }

    minutas = cargar_minutas()
    minutas.append(minuta)
    guardar_minutas(minutas)
    print(f"[BOT-INFORMES] Minuta {fecha_str} {hora_str} | fotos:{n_fotos} links:{n_links} | {contenido[:55]}")


# ── Loop principal ───────────────────────────────────────────────────────────

def run_bot():
    token = get_bot_token()
    if not token:
        print("[BOT-INFORMES] Sin INFORMES_BOT_TOKEN configurado — bot no iniciado.")
        return

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    print("[BOT-INFORMES] Bot de informes iniciado, monitoreando mensajes…")
    offset = _load_offset()

    while True:
        try:
            result = tg_get_updates(token, offset)
            for upd in result.get("result", []):
                msg = upd.get("message") or upd.get("channel_post")
                if msg:
                    try:
                        procesar_mensaje(token, msg)
                    except Exception as e:
                        print(f"[BOT-INFORMES] Error procesando mensaje: {e}")
                offset = upd["update_id"] + 1
                _save_offset(offset)
        except Exception as e:
            print(f"[BOT-INFORMES] Error polling: {e}")
            time.sleep(5)
