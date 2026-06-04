#!/usr/bin/env python3
"""
Script de verificación y recuperación de datos de minutas.
Útil para diagnosticar problemas de persistencia en Railway.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

_DATA = Path(os.environ.get("DATA_DIR", Path(__file__).parent.resolve()))
VENEZUELA_TZ = timezone(timedelta(hours=-4))

MINUTAS_FILE = _DATA / "minutas.json"
LOG_FILE = _DATA / "mensajes_log.jsonl"

print("=" * 70)
print("  VERIFICADOR DE DATOS - PPT")
print("=" * 70)
print()

# Mostrar directorio de datos
print(f"📁 Directorio de datos: {_DATA}")
print(f"   Existe: {'✓' if _DATA.is_dir() else '✗'}")
print()

# Verificar minutas.json
print("📋 minutas.json:")
if MINUTAS_FILE.is_file():
    try:
        with MINUTAS_FILE.open(encoding="utf-8") as f:
            minutas = json.load(f)
        print(f"   ✓ Existe")
        print(f"   ✓ Minutas guardadas: {len(minutas)}")
        print(f"   ✓ Tamaño: {MINUTAS_FILE.stat().st_size / 1024:.1f} KB")
        if minutas:
            print(f"   ✓ Primera minuta: {minutas[0].get('fecha')} {minutas[0].get('hora')}")
            print(f"   ✓ Última minuta: {minutas[-1].get('fecha')} {minutas[-1].get('hora')}")
    except Exception as e:
        print(f"   ✗ Error leyendo: {e}")
else:
    print(f"   ✗ NO EXISTE")
print()

# Verificar log persistente
print("📝 mensajes_log.jsonl (log permanente del bot):")
if LOG_FILE.is_file():
    try:
        contador = 0
        with LOG_FILE.open(encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    contador += 1
        print(f"   ✓ Existe")
        print(f"   ✓ Entradas en log: {contador}")
        print(f"   ✓ Tamaño: {LOG_FILE.stat().st_size / 1024:.1f} KB")
        print(f"   ✓ Este archivo NO se borra con reinicios")
    except Exception as e:
        print(f"   ✗ Error leyendo: {e}")
else:
    print(f"   ✗ NO EXISTE (el bot aún no ha procesado mensajes)")
print()

# Diagnostico
print("🔍 DIAGNÓSTICO:")
minutas_existe = MINUTAS_FILE.is_file()
log_existe = LOG_FILE.is_file()

if minutas_existe and int(MINUTAS_FILE.stat().st_size) > 100:
    print("   ✓ Datos persistiendo correctamente")
elif not minutas_existe and log_existe:
    print("   ⚠️  minutas.json se perdió, pero el log persiste")
    print("   → Usa /api/recuperar-minutas para restaurar")
elif not minutas_existe and not log_existe:
    print("   ⚠️  Sin datos aún. Espera a que el bot procese mensajes del grupo")
else:
    print("   ⚠️  Estado desconocido")

print()
print("=" * 70)
print("  Para recuperar minutas desde el log, ejecuta:")
print("  POST http://localhost:8000/api/recuperar-minutas")
print("=" * 70)
