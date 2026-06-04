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

_DATA        = Path(__file__).parent.resolve() / "data"
MEDIA_DIR    = _DATA / "informes_media"

# Asegurar que los directorios existen
_DATA.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
OFFSET_FILE  = _DATA / "informes_offset.json"
LOG_FILE     = _DATA / "mensajes_log.jsonl"   # registro permanente de mensajes
VENEZUELA_TZ = timezone(timedelta(hours=-4))
OBSERVACION_DEFAULT = (
    "La información fue notificada a la digna superioridad en tiempo real "
    "para su conocimiento, evaluación y fines consiguientes."
)


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


def parsear_lugar(texto):
    """Extrae LUGAR del texto CPNB-ZULIA."""
    m = re.search(r'LUGAR:\s*(.+?)(?:\n|$)', texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip('.')
    return ""


def parsear_fuente(texto):
    """Construye la fuente a partir del @usuario y plataforma detectados."""
    plat = "Telegram"
    if "instagram" in texto.lower():
        plat = "Instagram"
    elif "twitter" in texto.lower() or "x.com" in texto.lower():
        plat = "Twitter/X"
    elif "facebook" in texto.lower():
        plat = "Facebook"
    handles = re.findall(r'@[\w]+', texto)
    if handles:
        return f"Patrullaje cibernético realizado en la red social {plat}, usuario {handles[0]}"
    return f"Patrullaje cibernético realizado en la red social {plat}"


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


def _guardar_imagen_bytes(data: bytes, content_type: str, key: str) -> Path | None:
    """Guarda bytes de imagen en MEDIA_DIR con nombre único basado en hash del contenido.
    Retorna None si es una imagen muy pequeña (probablemente un placeholder)."""
    if len(data) < 10000:  # Ignorar imágenes < 10KB (probables placeholders)
        return None

    ct  = content_type.lower()
    ext = ".png" if "png" in ct else ".gif" if "gif" in ct else ".jpg"

    # Hash del contenido (deduplicación de imágenes idénticas)
    content_hash = hashlib.md5(data).hexdigest()[:14]
    fname = content_hash + ext
    dest  = MEDIA_DIR / fname

    # Si ya existe, no volver a guardar
    if dest.is_file():
        return dest

    try:
        dest.write_bytes(data)
        return dest
    except Exception as e:
        print(f"[BOT-INFORMES] Error guardando imagen: {e}")
        return None


def _descargar_imagen_url(img_url: str, base_url: str = "") -> Path | None:
    """Descarga una imagen desde img_url (resuelve rutas relativas con base_url).
    Valida que sea una URL de imagen válida."""
    if not img_url:
        return None

    img_url = img_url.strip()

    # Ignorar URLs que no son de imagen
    if any(x in img_url.lower() for x in ["logo", "placeholder", "icon", "ad-", "tracker", "pixel"]):
        return None

    # Resolver URLs relativas
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/") and base_url:
        from urllib.parse import urlparse
        p = urlparse(base_url)
        img_url = f"{p.scheme}://{p.netloc}{img_url}"

    # Validar que sea HTTP(S)
    if not img_url.startswith("http"):
        return None

    try:
        ir = requests.get(img_url, timeout=20, headers=_HEADERS, allow_redirects=True)
        ir.raise_for_status()

        # Validar que sea realmente imagen
        ct = ir.headers.get("content-type", "").lower()
        if "image" not in ct:
            return None

        return _guardar_imagen_bytes(ir.content, ir.headers.get("content-type", "image/jpeg"), img_url)
    except Exception as e:
        print(f"[BOT-INFORMES] Error descargando {img_url[:50]}: {type(e).__name__}")
    return None


def _extraer_imagen_youtube(url: str) -> Path | None:
    """Obtiene thumbnail de YouTube sin API - solo la mejor calidad."""
    m = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    if not m:
        return None
    vid = m.group(1)
    # Intentar solo maxresdefault (mejor calidad)
    thumb = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
    try:
        r = requests.get(thumb, timeout=10, headers=_HEADERS)
        if r.status_code == 200:
            result = _guardar_imagen_bytes(r.content, "image/jpeg", thumb)
            if result:
                return result
    except Exception:
        pass

    # Fallback a hqdefault si maxres no funciona
    thumb = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    try:
        r = requests.get(thumb, timeout=10, headers=_HEADERS)
        if r.status_code == 200:
            return _guardar_imagen_bytes(r.content, "image/jpeg", thumb)
    except Exception:
        pass
    return None


def _extraer_imagen_telegram(url: str) -> Path | None:
    """Intenta obtener la imagen de un post público de Telegram."""
    from bs4 import BeautifulSoup
    embed_url = re.sub(r'\?.*$', '', url) + "?embed=1&mode=tme"
    try:
        r = requests.get(embed_url, timeout=15, headers=_HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")

        # og:image en el embed
        for prop, attr in [("property", "og:image"), ("name", "og:image")]:
            tag = soup.find("meta", {prop: attr})
            if tag and tag.get("content"):
                img = _descargar_imagen_url(tag["content"], url)
                if img:
                    return img

        # Imagen dentro del widget del mensaje
        for cls in ("tgme_widget_message_photo_image", "tgme_widget_message_photo"):
            img = soup.find(["img", "i"], class_=re.compile(cls))
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    result = _descargar_imagen_url(src, url)
                    if result:
                        return result

        # background-image en style
        for tag in soup.find_all(style=re.compile(r"background-image")):
            m = re.search(r"url\(['\"]?(https?://[^'\")\s]+)['\"]?\)", tag.get("style", ""))
            if m:
                result = _descargar_imagen_url(m.group(1), url)
                if result:
                    return result
    except Exception as e:
        print(f"[BOT-INFORMES] Error Telegram {url[:50]}: {type(e).__name__}")
    return None


def _extraer_imagen_instagram(url: str) -> Path | None:
    """Extrae imagen de Instagram usando oembed o og:image."""
    try:
        # Intentar og:image primero (más rápido)
        r = requests.get(url, timeout=15, headers=_HEADERS)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        # og:image
        for prop in ["property", "name"]:
            tag = soup.find("meta", {prop: "og:image"})
            if tag and tag.get("content"):
                result = _descargar_imagen_url(tag["content"], url)
                if result:
                    return result
    except Exception as e:
        print(f"[BOT-INFORMES] Error Instagram {url[:50]}: {type(e).__name__}")
    return None


def _extraer_imagen_tiktok(url: str) -> Path | None:
    """Extrae imagen (thumbnail) de TikTok usando og:image."""
    try:
        r = requests.get(url, timeout=15, headers=_HEADERS)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        # og:image para TikTok
        tag = soup.find("meta", {"property": "og:image"})
        if not tag:
            tag = soup.find("meta", {"name": "og:image"})
        if tag and tag.get("content"):
            result = _descargar_imagen_url(tag["content"], url)
            if result:
                return result
    except Exception as e:
        print(f"[BOT-INFORMES] Error TikTok {url[:50]}: {type(e).__name__}")
    return None


def _extraer_imagen_og(url: str) -> Path | None:
    """Extrae og:image / twitter:image de cualquier página web.
    Intenta múltiples estrategias: meta tags, JSON-LD, y búsqueda en contenido."""
    from bs4 import BeautifulSoup
    import json as json_lib
    try:
        r = requests.get(url, timeout=15, headers=_HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Estrategia 1: Meta tags (og:image, twitter:image, etc.)
        preferencias = [
            ("property", "og:image"),
            ("name",     "og:image"),
            ("property", "twitter:image"),
            ("name",     "twitter:image"),
            ("itemprop", "image"),
        ]

        for prop, attr in preferencias:
            tags = soup.find_all("meta", {prop: attr})
            for tag in tags:
                img_url = tag.get("content", "").strip()
                if img_url:
                    result = _descargar_imagen_url(img_url, url)
                    if result:
                        return result

        # Estrategia 2: JSON-LD (usado por muchos sitios de noticias)
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json_lib.loads(script.string or "")
                # Buscar imagen en estructura de Article
                if isinstance(data, dict):
                    img_url = data.get("image") or (data.get("articleBody", {}) or {}).get("image")
                    if isinstance(img_url, str):
                        result = _descargar_imagen_url(img_url, url)
                        if result:
                            return result
                    elif isinstance(img_url, list) and img_url:
                        img_url = img_url[0] if isinstance(img_url[0], str) else img_url[0].get("url", "")
                        if img_url:
                            result = _descargar_imagen_url(img_url, url)
                            if result:
                                return result
            except Exception:
                pass

        # Estrategia 3: Buscar imágenes en contenedores comunes de artículos
        contenedores = [
            "article", "main", ".article", ".post", ".content", ".entry-content",
            "[role='main']", ".story", ".news-item"
        ]

        for selector in contenedores:
            try:
                contenedor = soup.select_one(selector)
                if not contenedor:
                    continue

                imgs = contenedor.find_all("img", limit=5)
                for img in imgs:
                    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
                    if src and len(src) > 15:
                        result = _descargar_imagen_url(src, url)
                        if result:
                            return result
            except Exception:
                pass

        # Estrategia 4: Buscar la primera imagen grande en toda la página
        for img in soup.find_all("img", limit=20):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if src and len(src) > 15:
                # Filtrar imágenes típicamente pequeñas
                alt = (img.get("alt") or "").lower()
                if any(x in alt for x in ["logo", "icon", "avatar", "ad"]):
                    continue
                result = _descargar_imagen_url(src, url)
                if result:
                    return result

    except Exception as e:
        print(f"[BOT-INFORMES] Error og:image {url[:50]}: {type(e).__name__}")
    return None


def extraer_og_image(url: str) -> Path | None:
    """Punto de entrada: detecta el tipo de URL y extrae la mejor imagen disponible."""
    if not url.startswith("http"):
        return None

    url = url.strip()
    result = None

    try:
        if "youtube.com" in url or "youtu.be" in url:
            result = _extraer_imagen_youtube(url)
        elif "t.me" in url or "telegram.me" in url:
            result = _extraer_imagen_telegram(url)
        elif "instagram.com" in url or "instagra.am" in url or "ig.me" in url:
            result = _extraer_imagen_instagram(url)
        elif "tiktok.com" in url or "vm.tiktok.com" in url or "vt.tiktok.com" in url:
            result = _extraer_imagen_tiktok(url)
        else:
            # Para cualquier otro sitio (noticias, etc.) usar og:image genérico
            result = _extraer_imagen_og(url)
    except Exception as e:
        print(f"[BOT-INFORMES] extraer_og_image({url[:50]}): {type(e).__name__}")

    if result:
        print(f"[BOT-INFORMES] ✓ Imagen: {result.name} ← {url[:65]}")
    else:
        print(f"[BOT-INFORMES] ✗ Sin imagen: {url[:65]}")
    return result


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

def generar_con_ia(texto, media_info="", lugar_hint="", fuente_hint=""):
    """Genera todos los campos de la minuta en lenguaje policial venezolano."""
    grok_key = get_grok_key()
    if not grok_key:
        return {
            "lugar":      lugar_hint or "Estado Zulia",
            "fuente":     fuente_hint or "Patrullaje cibernético en redes sociales",
            "incidencia": texto[:80] if texto else "(sin texto)",
            "hecho":      texto,
            "analisis":   "",
            "observacion": OBSERVACION_DEFAULT,
        }

    extra  = f"\nMEDIOS ADJUNTOS: {media_info}" if media_info else ""
    l_ctx  = f"\nLUGAR DETECTADO: {lugar_hint}" if lugar_hint else ""
    f_ctx  = f"\nFUENTE DETECTADA: {fuente_hint}" if fuente_hint else ""
    prompt = (
        "Eres un analista del CPNB-ZULIA (Cuerpo de Policía Nacional Bolivariana - Zulia), "
        "especializado en monitoreo de redes sociales e inteligencia digital venezolana.\n\n"
        "Redacta una minuta de monitoreo policial completa basándote en:\n\n"
        f"CONTENIDO: {texto}{extra}{l_ctx}{f_ctx}\n\n"
        "Responde ÚNICAMENTE con JSON válido:\n"
        "{\n"
        '  "lugar": "municipio/parroquia/estado donde ocurrió el hecho",\n'
        '  "fuente": "Patrullaje cibernético realizado en la red social [plataforma], usuario @[handle]",\n'
        '  "incidencia": "título breve del hecho en máximo 12 palabras",\n'
        '  "hecho": "narrativa iniciando con Mediante labores de patrullaje cibernético en la red social [X] se tuvo conocimiento... (3-5 oraciones formales)",\n'
        '  "analisis": "análisis del impacto e implicaciones institucionales (2-3 oraciones)",\n'
        f'  "observacion": "{OBSERVACION_DEFAULT}"\n'
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
    return {
        "lugar":      lugar_hint or "Estado Zulia",
        "fuente":     fuente_hint or "Patrullaje cibernético en redes sociales",
        "incidencia": texto[:80] if texto else "(sin texto)",
        "hecho":      texto,
        "analisis":   "",
        "observacion": OBSERVACION_DEFAULT,
    }


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


def _log_mensaje(msg, update_id=0):
    """Persiste el mensaje raw en mensajes_log.jsonl para reimportación futura."""
    texto = msg.get("text") or msg.get("caption") or ""
    fecha_ve, hora_ve = parsear_formato_cpnb(texto)
    ahora = datetime.now(VENEZUELA_TZ)
    if not fecha_ve:
        fecha_ve = ahora.strftime("%d/%m/%Y")
    if not hora_ve:
        hora_ve = ahora.strftime("%H:%M")
    entrada = {
        "update_id": update_id,
        "fecha_ve":  fecha_ve,
        "hora_ve":   hora_ve,
        "texto":     texto[:120],
        "raw":       msg,
    }
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[BOT-INFORMES] Error escribiendo log: {e}")


# ── Procesamiento de mensajes ────────────────────────────────────────────────

def _texto_duplicado(texto):
    """Devuelve True si ese texto_original ya existe en las minutas guardadas."""
    if not texto:
        return False
    from informes import cargar_minutas
    t = texto.strip()
    return any(m.get("texto_original", "").strip() == t for m in cargar_minutas())


def procesar_mensaje(token, msg):
    from informes import cargar_minutas, guardar_minutas

    texto = msg.get("text") or msg.get("caption") or ""

    # Ignorar mensajes sin contenido relevante
    if not texto and "photo" not in msg and "video" not in msg and "document" not in msg:
        return

    # Evitar duplicados
    if _texto_duplicado(texto):
        print(f"[BOT-INFORMES] Duplicado ignorado: {texto[:50]}")
        return

    media = []
    tiene_foto_directa = False

    # ── Foto directa adjunta al mensaje (PRIORIDAD) ──
    if "photo" in msg:
        try:
            p = tg_download_file(token, msg["photo"][-1]["file_id"])
            media.append({"tipo": "foto", "filename": p.name, "path": str(p)})
            tiene_foto_directa = True
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
                tiene_foto_directa = True
            except Exception as e:
                print(f"[BOT-INFORMES] Error documento: {e}")

    # ── Links: guardar + scraping de imagen (solo si NO hay foto directa) ──
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

        # Solo extraer imagen de URL si no hay foto directa
        if not tiene_foto_directa:
            img_path = extraer_og_image(url)
            if img_path:
                media.append({
                    "tipo":     "foto",
                    "filename": img_path.name,
                    "path":     str(img_path),
                    "fuente":   url,
                })
                tiene_foto_directa = True  # Solo 1 foto por minuta

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

    lugar_detectado  = parsear_lugar(texto)
    fuente_detectada = parsear_fuente(texto)

    ia = generar_con_ia(contenido, ", ".join(partes), lugar_detectado, fuente_detectada)

    minuta = {
        "fecha":          fecha_str,
        "hora":           hora_str,
        "cpnb":           "CPNB-ZULIA",
        "lugar":          ia.get("lugar", lugar_detectado or "Estado Zulia"),
        "fuente":         ia.get("fuente", fuente_detectada),
        "incidencia":     ia.get("incidencia", ""),
        "hecho":          ia.get("hecho", contenido),
        "analisis":       ia.get("analisis", ""),
        "observacion":    ia.get("observacion", OBSERVACION_DEFAULT),
        "media":          media,
        "texto_original": texto,
        "ia":             True,
    }

    minutas = cargar_minutas()
    minutas.append(minuta)
    guardar_minutas(minutas)
    print(f"[BOT-INFORMES] Minuta {fecha_str} {hora_str} | fotos:{n_fotos} links:{n_links} | {contenido[:55]}")


# ── Escaneo manual (importar del grupo) ─────────────────────────────────────

def escanear_grupo():
    """
    Recorre TODOS los mensajes pendientes del queue de Telegram (offset=0)
    y convierte en minutas los que no estén ya guardados.
    Retorna la cantidad de minutas nuevas importadas.
    """
    token = get_bot_token()
    if not token:
        return 0

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # Snapshot de textos ya existentes para deduplicar sin leer el archivo en cada iteración
    from informes import cargar_minutas
    existentes = {m.get("texto_original", "").strip() for m in cargar_minutas() if m.get("texto_original")}

    importadas = 0
    offset     = 0

    print("[BOT-INFORMES] Iniciando escaneo manual del grupo…")
    while True:
        try:
            result  = tg_get_updates(token, offset)
            updates = result.get("result", [])
            if not updates:
                break
            for upd in updates:
                msg = upd.get("message") or upd.get("channel_post")
                if msg:
                    _log_mensaje(msg, upd["update_id"])   # registro permanente
                    texto = (msg.get("text") or msg.get("caption") or "").strip()
                    tiene_media = "photo" in msg or "video" in msg or "document" in msg
                    if texto or tiene_media:
                        if texto not in existentes:
                            procesar_mensaje(token, msg)
                            existentes.add(texto)
                            importadas += 1
                offset = upd["update_id"] + 1
            _save_offset(offset)
            if len(updates) < 100:
                break
        except Exception as e:
            print(f"[BOT-INFORMES] Error escaneo: {e}")
            break

    print(f"[BOT-INFORMES] Escaneo terminado. {importadas} minuta(s) nueva(s).")
    return importadas


# ── Reimportación desde log persistente ─────────────────────────────────────

def fechas_en_log():
    """Devuelve lista de fechas únicas presentes en el log (más reciente primero)."""
    if not LOG_FILE.is_file():
        return []
    fechas = set()
    try:
        with LOG_FILE.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entrada = json.loads(linea)
                    fv = entrada.get("fecha_ve")
                    if fv:
                        fechas.add(fv)
                except Exception:
                    pass
    except Exception:
        pass
    return sorted(fechas, reverse=True)


def escanear_desde_log(fecha=None):
    """
    Reimporta mensajes del log persistente.
    Si fecha='dd/mm/yyyy' filtra por ese día; si fecha=None importa todos.
    Retorna número de minutas nuevas generadas.
    """
    if not LOG_FILE.is_file():
        return 0

    token = get_bot_token()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    from informes import cargar_minutas
    existentes = {m.get("texto_original", "").strip() for m in cargar_minutas() if m.get("texto_original")}

    importadas = 0
    print(f"[BOT-INFORMES] Reimportando desde log{f' ({fecha})' if fecha else ''}…")
    try:
        with LOG_FILE.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entrada = json.loads(linea)
                    if fecha and entrada.get("fecha_ve") != fecha:
                        continue
                    msg   = entrada.get("raw", {})
                    texto = (msg.get("text") or msg.get("caption") or "").strip()
                    tiene_media = "photo" in msg or "video" in msg or "document" in msg
                    if (texto or tiene_media) and texto not in existentes:
                        procesar_mensaje(token, msg)
                        existentes.add(texto)
                        importadas += 1
                except Exception as e:
                    print(f"[BOT-INFORMES] Error log entry: {e}")
    except Exception as e:
        print(f"[BOT-INFORMES] Error leyendo log: {e}")

    print(f"[BOT-INFORMES] Log: {importadas} minuta(s) nueva(s) importada(s).")
    return importadas


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
                    _log_mensaje(msg, upd["update_id"])   # registro permanente
                    try:
                        procesar_mensaje(token, msg)
                    except Exception as e:
                        print(f"[BOT-INFORMES] Error procesando mensaje: {e}")
                offset = upd["update_id"] + 1
                _save_offset(offset)
        except Exception as e:
            print(f"[BOT-INFORMES] Error polling: {e}")
            time.sleep(5)
