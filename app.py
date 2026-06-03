"""
app.py  --  Servidor web PWA para CPNB-ZULIA
Requiere:  pip install fastapi uvicorn aiofiles
Correr:    python app.py
"""
import json
import os
import socket
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

# En Railway: genera config.json desde variables de entorno si no existe
def _setup_config_from_env():
    cfg_path = ROOT / "config.json"
    token = os.environ.get("BOT_TOKEN")
    if not token:
        return
    if cfg_path.is_file():
        return
    cfg = {
        "bot_token":               token,
        "chat_id_gubernamentales": int(os.environ.get("CHAT_GUB", 0)),
        "chat_id_consulados":      int(os.environ.get("CHAT_CONS", 0)),
        "chat_id_reporte":         int(os.environ.get("CHAT_REPORTE", 0)),
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("config.json generado desde variables de entorno.")

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
    print("Ejecuta:  pip install python-pptx requests Pillow")
    sys.exit(1)

app = FastAPI(title="CPNB-ZULIA Monitor")
STATIC_DIR = ROOT / "static"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

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
            "slug":      lugar["slug"],
            "nombre":    lugar["nombre"],
            "coords":    lugar["coords"],
            "tiene_foto": foto is not None,
            "foto_url":  f"/api/foto/gub/{lugar['slug']}" if foto else None,
        })

    cons = []
    for lugar in LUGARES_CONS:
        foto = buscar_foto_de(lugar["slug"], CARPETA_CONS)
        cons.append({
            "slug":      lugar["slug"],
            "nombre":    lugar["nombre"],
            "coords":    lugar["coords"],
            "tiene_foto": foto is not None,
            "foto_url":  f"/api/foto/cons/{lugar['slug']}" if foto else None,
        })

    return {
        "gubernamentales":  gub,
        "consulados":       cons,
        "last_update_id":   estado.get("last_update_id", 0),
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


@app.post("/api/actualizar")
def actualizar_telegram():
    try:
        config = cargar_config()
    except SystemExit:
        raise HTTPException(503, "Falta config.json")
    try:
        estado = cargar_estado()
        sin_clasif, sustituciones = procesar_telegram(config, estado)
        return {
            "ok": True,
            "sin_clasificar": len(sin_clasif),
            "actualizadas":   len(sustituciones),
        }
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

    token = config.get("bot_token", "")
    if not token or token.startswith("PEGA_"):
        raise HTTPException(503, "bot_token no configurado en config.json")

    chat_id = config.get("chat_id_reporte")
    if not chat_id:
        raise HTTPException(400, "chat_id_reporte no definido en config.json")

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


# Rutas explícitas para archivos estáticos raíz
@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/manifest.json")
def manifest():
    return FileResponse(str(STATIC_DIR / "manifest.json"))

@app.get("/sw.js")
def service_worker():
    return FileResponse(str(STATIC_DIR / "sw.js"))

# Resto de archivos estáticos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
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
