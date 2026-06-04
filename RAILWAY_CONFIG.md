# Configuración de Railway para Persistencia de Datos

## Problema
Cuando Railway reinicia el contenedor, se pierden los datos guardados (minutas.json, imágenes, logs).

## Solución: Volumen Persistente

### Paso 1: En el Dashboard de Railway

1. Ve a tu proyecto en [railway.app](https://railway.app)
2. Selecciona el servicio (la app Python)
3. Abre la pestaña **"Settings"**
4. Busca la sección **"Volumes"** o **"Storage"**
5. Agrega un nuevo volumen con:
   - **Mount Path:** `/app/data`
   - **Size:** 1GB (o más, según necesites)

### Paso 2: Configuración de Variable de Entorno

El volumen creado debe ser referenciado por la app. En el dashboard de Railway:

1. Ve a **"Variables"** 
2. Agrega esta variable de entorno:
   ```
   DATA_DIR=/app/data
   ```

### Paso 3: Verify

Los archivos que se guardarán automáticamente en el volumen persistente:
- `minutas.json` - Minutas capturadas por el bot
- `informes_media/` - Imágenes descargadas
- `mensajes_log.jsonl` - Registro permanente de mensajes
- `informes_offset.json` - Offset del bot de Telegram
- `estado_telegram.json` - Estado de Telegram (opcional)

### Paso 4: Deploy

Después de configurar el volumen en Railway:
1. Haz un commit de los cambios en git
2. Haz push a GitHub
3. Railway hará auto-deploy
4. Los datos ahora persistirán entre reinicios ✓

## Verificación

Después del deploy:
1. Captura algunas minutas con el bot
2. Verifica que aparezcan en la UI
3. Reinicia el contenedor en Railway (Settings > Restart)
4. Verifica que las minutas sigan ahí

Si siguen ahí después del reinicio = ✓ Funciona!
