"""
app.py  --  Servidor web PWA para CPNB-ZULIA
"""
import json
import os
import socket
import sys
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

ROOT         = Path(__file__).parent.resolve()
_DATA_DIR    = ROOT / "data"
VENEZUELA_TZ = timezone(timedelta(hours=-4))
sys.path.insert(0, str(ROOT))

# Flag para asegurar que el bot solo se inicia una vez
_BOT_INICIADO = False


# ── Configuración desde variables de entorno ─────────────────────────────────

def _setup_config_from_env():
    cfg_path = ROOT / "config.json"
    if not os.environ.get("BOT_TOKEN"):
        return
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    changed = False
    for env_var, key, default in [
        ("BOT_TOKEN",           "bot_token",               ""),
        ("CHAT_GUB",            "chat_id_gubernamentales",  0),
        ("CHAT_CONS",           "chat_id_consulados",       0),
        ("CHAT_REPORTE",        "chat_id_reporte",          0),
        ("INFORMES_BOT_TOKEN",  "informes_bot_token",       ""),
        ("GROK_API_KEY",        "grok_api_key",             ""),
    ]:
        val = os.environ.get(env_var)
        if val is not None:
            val = val.strip()
            new_val = int(val) if isinstance(default, int) and val else (val or default)
            if cfg.get(key) != new_val:
                cfg[key] = new_val
                changed = True
    if changed:
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print("config.json actualizado desde variables de entorno.")


_setup_config_from_env()

try:
    from ppt import (
        LUGARES_GUB, LUGARES_CONS, CARPETA_GUB, CARPETA_CONS,
        PERSONAS, cargar_config, cargar_estado,
        procesar_telegram, buscar_foto_de,
        texto_reporte_consulados, texto_reporte_ministerio,
        tg_send_message, tg_send_media_group,
    )
except SystemExit:
    print("ERROR: faltan dependencias de ppt.py.")
    sys.exit(1)

from informes import (
    cargar_minutas, guardar_minutas, generar_docx, obtener_rango_horario,
    RENGLONES_SITUACION, EDS_MARACAIBO, generar_docx_situacion, recuperar_minutas_desde_log,
)

# Crear carpetas de datos al arrancar
CARPETA_GUB.mkdir(parents=True, exist_ok=True)
CARPETA_CONS.mkdir(parents=True, exist_ok=True)
(CARPETA_GUB / "sin_clasificar").mkdir(parents=True, exist_ok=True)
(CARPETA_CONS / "sin_clasificar").mkdir(parents=True, exist_ok=True)
(_DATA_DIR / "informes_media").mkdir(parents=True, exist_ok=True)

STATIC_DIR        = ROOT / "static"
INFORMES_MEDIA_DIR = _DATA_DIR / "informes_media"

app = FastAPI(title="CPNB-ZULIA Monitor")


@app.on_event("startup")
def start_informes_bot():
    global _BOT_INICIADO
    if _BOT_INICIADO:
        print("[APP] Bots ya están corriendo (evitando duplicados).")
        return
    try:
        from bot_informes import run_bot as run_bot_informes
        t1 = threading.Thread(target=run_bot_informes, daemon=True, name="bot-informes")
        t1.start()
        print("[APP] Bot de informes iniciado en hilo daemon.")
    except Exception as e:
        print(f"[APP] Bot de informes no iniciado: {e}")

    try:
        from bot_fotos import run_bot as run_bot_fotos
        t2 = threading.Thread(target=run_bot_fotos, daemon=True, name="bot-fotos")
        t2.start()
        print("[APP] Bot de fotos iniciado en hilo daemon.")
    except Exception as e:
        print(f"[APP] Bot de fotos no iniciado: {e}")

    _BOT_INICIADO = True


# ── API Monitor ──────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    try:
        cargar_config()
    except SystemExit:
        raise HTTPException(503, "Falta config.json en la carpeta del proyecto.")
    estado = cargar_estado()
    gub = []
    for lugar in LUGARES_GUB:
        foto = buscar_foto_de(lugar["slug"], CARPETA_GUB)
        gub.append({
            "slug":       lugar["slug"],
            "nombre":     lugar["nombre"],
            "coords":     lugar["coords"],
            "tiene_foto": foto is not None,
            "foto_url":   f"/api/foto/gub/{lugar['slug']}" if foto else None,
        })
    cons = []
    for lugar in LUGARES_CONS:
        foto = buscar_foto_de(lugar["slug"], CARPETA_CONS)
        cons.append({
            "slug":       lugar["slug"],
            "nombre":     lugar["nombre"],
            "coords":     lugar["coords"],
            "tiene_foto": foto is not None,
            "foto_url":   f"/api/foto/cons/{lugar['slug']}" if foto else None,
        })
    return {
        "gubernamentales": gub,
        "consulados":      cons,
        "last_update_id":  estado.get("last_update_id", 0),
    }


@app.get("/api/foto/{grupo}/{slug}")
def get_foto(grupo: str, slug: str):
    if grupo not in ("gub", "cons"):
        raise HTTPException(400, "grupo invalido")
    carpeta = CARPETA_GUB if grupo == "gub" else CARPETA_CONS
    foto = buscar_foto_de(slug, carpeta)
    if not foto:
        raise HTTPException(404, "Foto no encontrada")
    return FileResponse(str(foto))


@app.get("/api/media-informe/{filename}")
def get_media_informe(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "nombre inválido")
    path = INFORMES_MEDIA_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(str(path))


@app.post("/api/actualizar")
def actualizar_telegram():
    try:
        config = cargar_config()
    except SystemExit:
        raise HTTPException(503, "Falta config.json")
    try:
        estado = cargar_estado()
        sin_clasif, sustituciones = procesar_telegram(config, estado)
        return {"ok": True, "sin_clasificar": len(sin_clasif), "actualizadas": len(sustituciones)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/personas")
def get_personas():
    return {"personas": PERSONAS}


@app.post("/api/reporte/{tipo}")
def enviar_reporte(tipo: str, ci: str = Body(..., embed=True)):
    if tipo not in ("consulados", "ministerio"):
        raise HTTPException(400, "tipo debe ser 'consulados' o 'ministerio'")
    try:
        config = cargar_config()
    except SystemExit:
        raise HTTPException(503, "Falta config.json")
    token   = config.get("bot_token", "")
    chat_id = config.get("chat_id_reporte")
    if not token or not chat_id:
        raise HTTPException(503, "bot_token o chat_id_reporte no configurado")
    persona = next((p for p in PERSONAS if p["ci"] == ci), None)
    if not persona:
        raise HTTPException(400, f"No se encontró persona con CI {ci}")
    fotos = []
    try:
        if tipo == "consulados":
            for l in LUGARES_CONS:
                p = buscar_foto_de(l["slug"], CARPETA_CONS)
                if p:
                    fotos.append(str(p))
            texto = texto_reporte_consulados(persona)
        else:
            for l in LUGARES_GUB:
                p = buscar_foto_de(l["slug"], CARPETA_GUB)
                if p:
                    fotos.append(str(p))
            texto = texto_reporte_ministerio(persona)
        if fotos:
            tg_send_media_group(token, chat_id, fotos, caption=texto)
        else:
            tg_send_message(token, chat_id, texto)
        return {"ok": True, "fotos_enviadas": len(fotos)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── API Minutas / Informes ────────────────────────────────────────────────────

class MinutaIn(BaseModel):
    fecha: str
    hora: str
    hecho: str
    cpnb: Optional[str] = "CPNB-ZULIA"
    analisis: Optional[str] = ""
    observacion: Optional[str] = ""


@app.get("/api/minutas")
def get_minutas():
    ahora = datetime.now(VENEZUELA_TZ)
    rango, tipo = obtener_rango_horario()
    return {
        "minutas":  cargar_minutas(),
        "rango":    rango,
        "tipo":     tipo,
        "fecha_ve": ahora.strftime("%d/%m/%Y"),
        "hora_ve":  ahora.strftime("%H:%M"),
    }


@app.post("/api/minutas")
def add_minuta(m: MinutaIn):
    minutas = cargar_minutas()
    minutas.append(m.model_dump())
    guardar_minutas(minutas)
    return {"ok": True, "total": len(minutas)}


@app.delete("/api/minutas")
def clear_minutas():
    guardar_minutas([])
    return {"ok": True}


@app.delete("/api/minutas/{idx}")
def delete_minuta(idx: int):
    minutas = cargar_minutas()
    if idx < 0 or idx >= len(minutas):
        raise HTTPException(400, "Índice fuera de rango")
    minutas.pop(idx)
    guardar_minutas(minutas)
    return {"ok": True, "total": len(minutas)}


@app.get("/api/fechas-log")
def get_fechas_log():
    try:
        from bot_informes import fechas_en_log
        return {"fechas": fechas_en_log()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/escanear-grupo")
def escanear_grupo_api(fecha: Optional[str] = Body(None, embed=True)):
    try:
        from bot_informes import escanear_grupo, escanear_desde_log
        if fecha:
            importadas = escanear_desde_log(fecha)
        else:
            importadas = escanear_grupo()
        return {"ok": True, "importadas": importadas}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/recuperar-minutas")
def recuperar_minutas_api():
    """Recupera todas las minutas desde el log persistente del bot.
    Útil si minutas.json se pierde o se corrompe."""
    try:
        minutas_antes = len(cargar_minutas())
        importadas = recuperar_minutas_desde_log()
        minutas_ahora = len(cargar_minutas())
        return {
            "ok": True,
            "minutas_antes": minutas_antes,
            "minutas_ahora": minutas_ahora,
            "nuevas_importadas": importadas,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/estado-persistencia")
def estado_persistencia_api():
    """Muestra el estado de los archivos de datos persistentes."""
    from pathlib import Path
    import os

    data_dir = _DATA_DIR
    estado = {
        "data_dir": str(data_dir),
        "archivos": {}
    }

    archivos_importantes = [
        "minutas.json",
        "mensajes_log.jsonl",
        "informes_offset.json",
    ]

    for archivo in archivos_importantes:
        ruta = data_dir / archivo
        if ruta.is_file():
            tamaño = os.path.getsize(ruta)
            estado["archivos"][archivo] = {
                "existe": True,
                "tamaño_bytes": tamaño,
                "ruta": str(ruta)
            }
        else:
            estado["archivos"][archivo] = {
                "existe": False,
                "ruta": str(ruta)
            }

    # Contador de minutas actuales
    estado["minutas_totales"] = len(cargar_minutas())

    return estado


@app.post("/api/resetear-offset")
def resetear_offset_api():
    """Elimina el archivo de offset del bot para resolver errores 409."""
    from pathlib import Path
    try:
        offset_file = _DATA_DIR / "informes_offset.json"
        if offset_file.is_file():
            offset_file.unlink()
            print("[API] Offset del bot reseteado.")
            return {"ok": True, "mensaje": "Offset reseteado. El bot volverá a sincronizarse."}
        else:
            return {"ok": True, "mensaje": "El archivo de offset no existía."}
    except Exception as e:
        raise HTTPException(500, f"Error reseteando offset: {e}")


@app.get("/api/renglones")
def get_renglones():
    return {
        "renglones": RENGLONES_SITUACION + ["ACCIDENTES DE TRÁNSITO"],
        "eds": EDS_MARACAIBO,
    }


class SituacionIn(BaseModel):
    asignaciones: dict            # {"0": "MONITOREO", "3": "SUCESOS", ...}
    homicidios: Optional[int] = 0
    eds_estado: Optional[dict] = None  # {"E/S MILAGROS": "NO FUNCIONANDO", ...}


@app.post("/api/generar-situacion")
def api_generar_situacion(data: SituacionIn):
    minutas = cargar_minutas()
    if not any(v for v in data.asignaciones.values()):
        raise HTTPException(400, "Asigna al menos una minuta a un renglón")
    try:
        eds = {eds: "FUNCIONANDO" for eds in EDS_MARACAIBO}
        if data.eds_estado:
            eds.update(data.eds_estado)
        ruta = generar_docx_situacion(minutas, data.asignaciones, data.homicidios or 0, eds)
        return FileResponse(
            str(ruta),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=ruta.name,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/generar-informe")
def api_generar_informe():
    minutas = cargar_minutas()
    if not minutas:
        raise HTTPException(400, "No hay minutas guardadas")
    try:
        ruta = generar_docx(minutas)
        return FileResponse(
            str(ruta),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=ruta.name,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Archivos estáticos ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/manifest.json")
def manifest():
    return FileResponse(str(STATIC_DIR / "manifest.json"))

@app.get("/sw.js")
def service_worker():
    return FileResponse(str(STATIC_DIR / "sw.js"))

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Arranque ─────────────────────────────────────────────────────────────────

def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    ip   = _local_ip()
    print("=" * 55)
    print("  CPNB-ZULIA Monitor  --  servidor iniciado")
    print(f"  Local:   http://localhost:{port}")
    if port == 8000:
        print(f"  Movil:   http://{ip}:{port}")
        print("  (Usa la URL 'Movil' en tu telefono, misma WiFi)")
    print("=" * 55)
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
