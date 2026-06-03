import json, importlib.util
from pathlib import Path
root = Path(__file__).parent
cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('mod', str(root / 'generar_ppt_cpnb.py.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
responsable = mod.elegir_responsable()
# Simular envío: buscar cualquier foto existente en carpetas y enviar as grouped
cons = list((root / 'fotos_consulados').glob('*')) if (root / 'fotos_consulados').exists() else []
gub = list((root / 'fotos_gubernamentales').glob('*')) if (root / 'fotos_gubernamentales').exists() else []

chat = cfg.get('chat_id_reporte')
token = cfg.get('bot_token')
if not chat or not token:
    print('Falta config')
    raise SystemExit(1)

if cons:
    print('Enviando texto consulados')
    mod.tg_send_message(token, chat, mod.REPORTE_CONSULADOS.format(**responsable))
    for p in cons[:5]:
        print('enviando', p)
        mod.tg_send_photo(token, chat, str(p))

if any(p.name.startswith('08_ministerio_publico') for p in gub):
    print('Enviando texto ministerio')
    mod.tg_send_message(token, chat, mod.REPORTE_MINISTERIO.format(**responsable))
    for p in [p for p in gub if p.name.startswith('08_ministerio_publico')]:
        print('enviando', p)
        mod.tg_send_photo(token, chat, str(p))

print('Prueba fotos completa')
