import json
import importlib.util
from pathlib import Path

root = Path(__file__).parent
cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))

spec = importlib.util.spec_from_file_location('mod', str(root / 'generar_ppt_cpnb.py.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

responsable = mod.elegir_responsable()
text_cons = mod.REPORTE_CONSULADOS.format(**responsable)
text_min = mod.REPORTE_MINISTERIO.format(**responsable)

token = cfg.get('bot_token')
chat = cfg.get('chat_id_reporte')

if not token or not chat:
    print('Falta bot_token o chat_id_reporte en config.json')
    raise SystemExit(1)

print('Enviando mensaje de prueba (Consulados)...')
try:
    mod.tg_send_message(token, chat, text_cons)
    print('OK: Consulados enviado')
except Exception as e:
    print('ERROR enviando consulados:', e)

print('Enviando mensaje de prueba (Ministerio Público)...')
try:
    mod.tg_send_message(token, chat, text_min)
    print('OK: Ministerio enviado')
except Exception as e:
    print('ERROR enviando ministerio:', e)
