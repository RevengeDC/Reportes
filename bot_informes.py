"""
bot_informes.py — Bot Telegram que recibe contenido y genera minutas con IA Grok
Flujo: mensaje Telegram → descarga media → Grok AI → minuta guardada automáticamente
"""
import json
import os
import re
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

_DATA      = Path(os.environ.get("DATA_DIR", Path(__file__).parent.resolve()))
MEDIA_DIR  = _DATA / "informes_media"
OFFSET_FILE = _DATA / "informes_offset.json"
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
    return os.environ.get("INFORMES_BOT_TOKEN") or _cfg().get("informes_bot_token", "")


def get_grok_key():
    return os.environ.get("GROK_API_KEY") or _cfg().get("grok_api_key", "")


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
    ext  = Path(file_path).suffix or ".bin"
    raw  = requests.get(
        f"https://api.telegram.org/file/bot{token}/{file_path}",
        timeout=60,
    )
    raw.raise_for_status()
    dest = MEDIA_DIR / f"{file_id}{ext}"
    dest.write_bytes(raw.content)
    return dest


# ── Grok AI ──────────────────────────────────────────────────────────────────

def generar_con_ia(texto, media_info=""):
    """Llama a Grok para generar Hecho, Análisis y Observación en lenguaje policial."""
    grok_key = get_grok_key()
    if not grok_key:
        return {"hecho": texto, "analisis": "", "observacion": ""}

    extra  = f"\nMEDIOS ADJUNTOS: {media_info}" if media_info else ""
    prompt = (
        "Eres un analista del CPNB-ZULIA (Cuerpo de Policía Nacional Bolivariana - Zulia), "
        "especializado en monitoreo de redes sociales e inteligencia digital venezolana.\n\n"
        "Basándote en el contenido recibido, redacta una minuta de monitoreo "
        "en formato policial profesional venezolano:\n\n"
        f"CONTENIDO: {texto}{extra}\n\n"
        "Responde ÚNICAMENTE con JSON válido (sin texto fuera del JSON):\n"
        "{\n"
        '  "hecho": "descripción factual objetiva en lenguaje policial formal (2-4 oraciones)",\n'
        '  "analisis": "análisis del impacto, contexto e implicaciones (2-3 oraciones)",\n'
        '  "observacion": "recomendaciones operativas y acciones de seguimiento (1-2 oraciones)"\n'
        "}"
    )

    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 600,
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
    media = []

    # Foto (mayor resolución disponible)
    if "photo" in msg:
        try:
            p = tg_download_file(token, msg["photo"][-1]["file_id"])
            media.append({"tipo": "foto", "filename": p.name, "path": str(p)})
        except Exception as e:
            print(f"[BOT-INFORMES] Error foto: {e}")

    # Video
    if "video" in msg:
        try:
            p = tg_download_file(token, msg["video"]["file_id"])
            media.append({"tipo": "video", "filename": p.name, "path": str(p)})
        except Exception as e:
            print(f"[BOT-INFORMES] Error video: {e}")

    # Documento / imagen adjunta
    if "document" in msg:
        mime = msg["document"].get("mime_type", "")
        if "image" in mime:
            try:
                p = tg_download_file(token, msg["document"]["file_id"])
                media.append({"tipo": "foto", "filename": p.name, "path": str(p)})
            except Exception as e:
                print(f"[BOT-INFORMES] Error doc-imagen: {e}")

    # Links en entities / caption_entities
    full_text = texto
    for ent in msg.get("entities", []) + msg.get("caption_entities", []):
        if ent["type"] == "url":
            url = full_text[ent["offset"]: ent["offset"] + ent["length"]]
            media.append({"tipo": "link", "url": url})
        elif ent["type"] == "text_link":
            media.append({"tipo": "link", "url": ent.get("url", "")})

    if not texto and not media:
        return

    # Fecha / hora Venezuela
    ahora     = datetime.now(VENEZUELA_TZ)
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str  = ahora.strftime("%H:%M")

    # Resumen de medios para el prompt de IA
    fotos  = sum(1 for m in media if m["tipo"] == "foto")
    videos = sum(1 for m in media if m["tipo"] == "video")
    links  = sum(1 for m in media if m["tipo"] == "link")
    partes = []
    if fotos:  partes.append(f"{fotos} foto(s)")
    if videos: partes.append(f"{videos} video(s)")
    if links:  partes.append(f"{links} enlace(s)")

    ia = generar_con_ia(
        texto or "(contenido multimedia sin texto)",
        ", ".join(partes),
    )

    minuta = {
        "fecha":          fecha_str,
        "hora":           hora_str,
        "cpnb":           "CPNB-ZULIA",
        "hecho":          ia.get("hecho", texto),
        "analisis":       ia.get("analisis", ""),
        "observacion":    ia.get("observacion", ""),
        "media":          media,
        "texto_original": texto,
        "ia":             True,
    }

    minutas = cargar_minutas()
    minutas.append(minuta)
    guardar_minutas(minutas)
    print(f"[BOT-INFORMES] Minuta guardada {fecha_str} {hora_str} | {texto[:60]}")


# ── Loop principal ───────────────────────────────────────────────────────────

def run_bot():
    token = get_bot_token()
    if not token:
        print("[BOT-INFORMES] Sin INFORMES_BOT_TOKEN configurado — bot no iniciado.")
        return

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    print("[BOT-INFORMES] Bot de informes iniciado, escuchando mensajes…")
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
