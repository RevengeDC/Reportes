"""
informes.py — Lógica de minutas e informes DOCX para la PWA
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DATA        = Path(os.environ.get("DATA_DIR", Path(__file__).parent.resolve()))
MINUTAS_FILE = _DATA / "minutas.json"
VENEZUELA_TZ = timezone(timedelta(hours=-4))

ANALISIS_TEXTOS = [
    "La información difundida en redes sociales representa un monitoreo continuo de eventos relevantes en el estado Zulia, permitiendo evaluar dinámicas sociales, políticas e institucionales.",
    "Este reporte contribuye a la comprensión del panorama informativo y el impacto de las acciones institucionales en la opinión pública.",
    "El análisis de contenidos en plataformas digitales permite identificar tendencias, evaluar alcance de mensajes y respuestas ciudadanas.",
]

OBSERVACION_TEXTOS = [
    "Se recomienda continuar con el monitoreo permanente de redes sociales y fuentes informativas para mantener actualizado el panorama situacional del estado.",
    "Es importante mantener vigilancia sobre la evolución de estos eventos y su potencial impacto en la dinámica social de la región.",
]

MESES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
         "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]


# ── Persistencia de minutas ──────────────────────────────────────────────────

def cargar_minutas():
    try:
        if MINUTAS_FILE.is_file():
            with MINUTAS_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def guardar_minutas(minutas):
    MINUTAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MINUTAS_FILE.open("w", encoding="utf-8") as f:
        json.dump(minutas, f, ensure_ascii=False, indent=2)


# ── Fechas y rangos (hora Venezuela UTC-4) ───────────────────────────────────

def obtener_fecha_formato(fecha=None):
    if fecha is None:
        fecha = datetime.now(VENEZUELA_TZ)
    return f"{fecha.day} DE {MESES[fecha.month - 1]} {fecha.year}"


def obtener_rango_horario():
    ahora = datetime.now(VENEZUELA_TZ)
    h = ahora.hour
    if 8 <= h < 17:
        f = obtener_fecha_formato(ahora)
        return f"{f} 08:00HRS – {f} 17:00HRS", "diurno"
    elif h >= 17:
        f1 = obtener_fecha_formato(ahora)
        f2 = obtener_fecha_formato(ahora + timedelta(days=1))
        return f"{f1} 17:00HRS – {f2} 08:00HRS", "nocturno"
    else:
        f1 = obtener_fecha_formato(ahora - timedelta(days=1))
        f2 = obtener_fecha_formato(ahora)
        return f"{f1} 17:00HRS – {f2} 08:00HRS", "nocturno"


def nombre_archivo_informe():
    hoy = datetime.now(VENEZUELA_TZ)
    return f"INFORME_0800HRS_ENTORNO_ZULIA_{str(hoy.day).zfill(2)}{str(hoy.month).zfill(2)}{hoy.year}.docx"


# ── Generación del DOCX ──────────────────────────────────────────────────────

def generar_docx(minutas):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    ahora = datetime.now(VENEZUELA_TZ)

    doc = Document()
    for sec in doc.sections:
        sec.top_margin    = Inches(1)
        sec.bottom_margin = Inches(1)
        sec.left_margin   = Inches(1)
        sec.right_margin  = Inches(1)

    # CONFIDENCIAL
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("CONFIDENCIAL")
    r.bold = True; r.font.size = Pt(16); r.font.color.rgb = RGBColor(204, 0, 0)

    # TÍTULO
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("INFORME ESPECIAL")
    r.bold = True; r.font.size = Pt(14)

    doc.add_paragraph(f"FECHA: {obtener_fecha_formato(ahora)}")
    doc.add_paragraph("LUGAR: Estado ZULIA")
    doc.add_paragraph("ASUNTO: Monitoreo")

    p = doc.add_paragraph()
    p.add_run("Ámbito Social").bold = True

    for idx, m in enumerate(minutas):
        p = doc.add_paragraph()
        p.add_run(m.get("cpnb", "CPNB-ZULIA")).bold = True

        doc.add_paragraph(f"FECHA: {m.get('fecha', '')}")
        doc.add_paragraph(f"HORA: {m.get('hora', '')}")
        doc.add_paragraph("")

        p = doc.add_paragraph()
        p.add_run("REPORTE DE REDES").bold = True
        doc.add_paragraph(m.get("hecho", ""))

        p = doc.add_paragraph()
        p.add_run("ANALISIS:").bold = True
        for linea in (m.get("analisis") or "\n".join(ANALISIS_TEXTOS)).split("\n"):
            if linea.strip():
                doc.add_paragraph(linea.strip())

        p = doc.add_paragraph()
        p.add_run("OBSERVACION:").bold = True
        for linea in (m.get("observacion") or "\n".join(OBSERVACION_TEXTOS)).split("\n"):
            if linea.strip():
                doc.add_paragraph(linea.strip())

        # Fotografías adjuntas
        fotos = [x for x in m.get("media", []) if x.get("tipo") == "foto"]
        if fotos:
            p = doc.add_paragraph()
            p.add_run("EVIDENCIA FOTOGRÁFICA:").bold = True
            for foto in fotos:
                path = Path(foto.get("path", ""))
                if path.is_file():
                    try:
                        doc.add_picture(str(path), width=Inches(5.5))
                    except Exception:
                        doc.add_paragraph(f"[Imagen: {foto.get('filename', 'foto')}]")
                else:
                    doc.add_paragraph(f"[Imagen no disponible: {foto.get('filename', '')}]")

        # Videos y enlaces
        otros = [x for x in m.get("media", []) if x.get("tipo") in ("video", "link")]
        if otros:
            p = doc.add_paragraph()
            p.add_run("REFERENCIAS:").bold = True
            for item in otros:
                if item["tipo"] == "video":
                    doc.add_paragraph(f"VIDEO: {item.get('filename', 'archivo de video')}")
                elif item["tipo"] == "link":
                    doc.add_paragraph(f"ENLACE: {item.get('url', '')}")

        if idx < len(minutas) - 1:
            doc.add_paragraph()

    # Electricidad
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.add_run("Electricidad:").bold = True
    doc.add_paragraph(
        "En el estado Zulia, se reporta que la capacidad operativa del sistema eléctrico se mantiene en un 60%, "
        "lo que indica un nivel de funcionamiento estable pero todavía por debajo de la plena capacidad; esta "
        "condición requiere monitoreo constante para prevenir interrupciones y garantizar la continuidad del "
        "suministro tanto a nivel residencial como industrial."
    )

    ruta = _DATA / nombre_archivo_informe()
    doc.save(str(ruta))
    return ruta
