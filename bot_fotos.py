"""
bot_fotos.py — Bot Telegram para capturar fotos de Estaciones de Servicio y Hospitales
Flujo: mensaje con foto + etiqueta (EDS/HOSPITAL) → descarga foto → guarda en carpeta específica
"""
import json
import os
import re
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

_DATA = Path(os.environ.get("DATA_DIR", Path(__file__).parent.resolve() / "data"))
FOTOS_EDS_DIR = _DATA / "fotos_eds"
FOTOS_HOSPITALES_DIR = _DATA / "fotos_hospitales"
OFFSET_FILE = _DATA / "fotos_offset.json"
VENEZUELA_TZ = timezone(timedelta(hours=-4))

# Asegurar que los directorios existen
FOTOS_EDS_DIR.mkdir(parents=True, exist_ok=True)
FOTOS_HOSPITALES_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
}


def _cfg():
    path = Path(__file__).parent / "config.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_fotos_bot_token():
    v = os.environ.get("FOTOS_BOT_TOKEN") or _cfg().get("fotos_bot_token", "")
    return v.strip()


def detectar_tipo_y_nombre(texto):
    """Detecta si la foto es de EDS o HOSPITAL y extrae el nombre específico.
    Retorna tupla: (tipo, nombre_slug) o (None, None)"""
    if not texto:
        return None, None

    texto_lower = texto.lower()

    # Mapeo de nombres de EDS a slugs
    eds_mapping = {
        "servicios populares": "eds_servicios_populares",
        "automotriz": "eds_automotriz",
        "milagros": "eds_milagros",
        "calzada": "eds_calzada",
        "pichincha": "eds_pichincha",
        "nigale": "eds_nigale",
        "carmen": "eds_carmen",
        "delicias": "eds_delicias",
    }

    # Mapeo de nombres de Hospitales a slugs
    hospitales_mapping = {
        "central": "hospital_central",
        "clínico": "hospital_clinico",
        "clinico": "hospital_clinico",
        "pediatría": "hospital_pediatria",
        "pediatria": "hospital_pediatria",
        "cardiología": "hospital_cardiologia",
        "cardiologia": "hospital_cardiologia",
        "los andes": "clinica_los_andes",
        "andes": "clinica_los_andes",
        "del este": "clinica_del_este",
        "este": "clinica_del_este",
    }

    # Detectar EDS
    if re.search(r'(e[\./]?s[\./]?|estacion.*servicio|gasolinera|bencinera|bomba|surtidor)', texto_lower):
        # Buscar nombre específico
        for nombre_clave, slug in eds_mapping.items():
            if nombre_clave in texto_lower:
                return "eds", slug
        return "eds", None

    # Detectar HOSPITAL
    if re.search(r'(hospital|clinica|dispensario|centro.*salud)', texto_lower):
        # Buscar nombre específico
        for nombre_clave, slug in hospitales_mapping.items():
            if nombre_clave in texto_lower:
                return "hospital", slug
        return "hospital", None

    # Detectar por emojis
    if "⛽" in texto or "🛢" in texto:
        return "eds", None
    if "🏥" in texto or "⚕️" in texto:
        return "hospital", None

    return None, None


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
    return raw.content, ext


def _load_offset():
    if OFFSET_FILE.is_file():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def _save_offset(v):
    OFFSET_FILE.write_text(str(v))


def procesar_mensaje(token, msg):
    """Procesa mensaje con foto y la clasifica como EDS o HOSPITAL con identificación específica."""

    # Solo procesar si hay foto
    if "photo" not in msg:
        return False

    texto = msg.get("caption", "")
    tipo, slug = detectar_tipo_y_nombre(texto)

    if not tipo:
        print(f"[BOT-FOTOS] Foto sin clasificación clara: {texto[:50]}")
        return False

    try:
        # Descargar foto
        data, ext = tg_download_file(token, msg["photo"][-1]["file_id"])

        # Determinar carpeta destino
        if tipo == "eds":
            destino = FOTOS_EDS_DIR
            tipo_nombre = "EDS"
        else:
            destino = FOTOS_HOSPITALES_DIR
            tipo_nombre = "HOSPITAL"

        # Generar nombre de archivo: slug_timestamp.ext (sin slug si no se identificó)
        ahora = datetime.now(VENEZUELA_TZ)
        if slug:
            filename = f"{slug}_{ahora.strftime('%Y%m%d_%H%M%S')}{ext}"
            identificacion = f"{tipo_nombre} ({slug})"
        else:
            # Si no se identificó, usar el texto del caption limpio
            nombre_limpio = texto.strip()[:30].replace("/", "_").replace("\\", "_")
            filename = f"{tipo_nombre}_{nombre_limpio}_{ahora.strftime('%Y%m%d_%H%M%S')}{ext}"
            identificacion = f"{tipo_nombre}: {nombre_limpio}"

        ruta = destino / filename
        ruta_metadata = destino / (filename.replace(ext, ".txt"))

        # Guardar foto
        with ruta.open("wb") as f:
            f.write(data)

        # Guardar caption como metadata (para mostrar nombre en UI)
        with ruta_metadata.open("w", encoding="utf-8") as f:
            f.write(texto.strip())

        print(f"[BOT-FOTOS] ✓ {identificacion}: {filename}")
        return True

    except Exception as e:
        print(f"[BOT-FOTOS] Error procesando foto: {e}")
        return False


def escanear_grupo_fotos():
    """Escanea manualmente todas las fotos del grupo (sin offset)."""
    token = get_fotos_bot_token()
    if not token:
        return 0

    FOTOS_EDS_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_HOSPITALES_DIR.mkdir(parents=True, exist_ok=True)

    procesadas = 0
    offset = 0

    print("[BOT-FOTOS] Iniciando escaneo manual del grupo…")
    while True:
        try:
            result = tg_get_updates(token, offset)
            updates = result.get("result", [])
            if not updates:
                break
            for upd in updates:
                msg = upd.get("message") or upd.get("channel_post")
                if msg and procesar_mensaje(token, msg):
                    procesadas += 1
                offset = upd["update_id"] + 1
            _save_offset(offset)
            if len(updates) < 100:
                break
        except Exception as e:
            print(f"[BOT-FOTOS] Error escaneo: {e}")
            break

    print(f"[BOT-FOTOS] Escaneo terminado. {procesadas} foto(s) nueva(s).")
    return procesadas


def run_bot():
    """Loop principal del bot de fotos."""
    token = get_fotos_bot_token()
    if not token:
        print("[BOT-FOTOS] Sin FOTOS_BOT_TOKEN configurado — bot no iniciado.")
        return

    FOTOS_EDS_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_HOSPITALES_DIR.mkdir(parents=True, exist_ok=True)

    print("[BOT-FOTOS] Bot de fotos iniciado, monitoreando fotos…")
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
                        print(f"[BOT-FOTOS] Error procesando mensaje: {e}")
                offset = upd["update_id"] + 1
                _save_offset(offset)
        except Exception as e:
            print(f"[BOT-FOTOS] Error polling: {e}")
            time.sleep(5)
