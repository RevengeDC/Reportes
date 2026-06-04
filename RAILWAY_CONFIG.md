# Configuración de Railway para Persistencia de Datos

## ✅ Estrategia Actual (Recomendada)

La app ahora guarda datos en una carpeta `data/` que **persiste entre reinicios** en Railway sin necesidad de volúmenes complejos.

### Archivos que persisten:
- `data/minutas.json` - Minutas capturadas por el bot
- `data/informes_media/` - Imágenes descargadas
- `data/mensajes_log.jsonl` - Registro permanente de mensajes
- `data/informes_offset.json` - Offset del bot de Telegram

---

## 🔄 Cómo funciona la Persistencia

1. **En Railway**, la carpeta `data/` se crea en `/app/data` durante la ejecución
2. **Entre reinicios**, Railway mantiene esta carpeta intacta (no hace clean build automático)
3. **Si Railway hace un deploy limpio**, se pierden los datos (raro)
   - Para recuperarlos: `POST /api/recuperar-minutas`

---

## 📋 Checklist

- ✅ Variable `DATA_DIR=/app/data` configurada en Railway
- ✅ Carpeta `data/` ignorada en `.gitignore`
- ✅ `railway.toml` configurado correctamente
- ✅ Endpoint `/api/recuperar-minutas` disponible como respaldo

---

## 🧪 Verificar que funcione

Abre en tu navegador:
```
https://tu-app.up.railway.app/api/estado-persistencia
```

Debería mostrar:
```json
{
  "data_dir": "/app/data",
  "minutas_totales": N,
  "archivos": {
    "minutas.json": {"existe": true, "tamaño_bytes": ...}
  }
}
```

Si `existe: false`, los datos se están perdiendo. En ese caso, contactar a Railway support.

---

## 🔧 Si necesitas recuperar datos

Aunque Railway ahora mantiene persistencia, si algo falla:

```
POST https://tu-app.up.railway.app/api/recuperar-minutas
```

Esto reconstruye `minutas.json` desde el log permanente del bot.
