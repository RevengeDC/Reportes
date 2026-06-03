import json
import importlib.util
from pathlib import Path

root = Path('c:/Users/Admin/Desktop/PPT')
config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('mod', root / 'generar_ppt_cpnb.py.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

chat = config.get('chat_id_reporte')
token = config.get('bot_token')
if not chat or not token:
    raise SystemExit('Missing bot_token or chat_id_reporte in config.json')

responsable = mod.elegir_responsable()
cons_photos = sorted(str(p) for p in (root / 'fotos_consulados').glob('*.jpg'))
min_photos = sorted(str(p) for p in (root / 'fotos_gubernamentales').glob('*.jpg') if p.name.startswith('08_ministerio_publico'))

print('Consulados photos:', len(cons_photos))
print('Ministerio photos:', len(min_photos))

if cons_photos:
    print('Sending consulados group...')
    mod.tg_send_media_group(token, chat, cons_photos, caption=mod.REPORTE_CONSULADOS.format(**responsable))
    print('Consulados group sent')

if min_photos:
    print('Sending Ministerio Público group...')
    mod.tg_send_media_group(token, chat, min_photos, caption=mod.REPORTE_MINISTERIO.format(**responsable))
    print('Ministerio Público group sent')
