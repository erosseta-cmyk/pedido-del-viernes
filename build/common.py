# Utilidades compartidas: normalizar nombres y leer precios de cada proveedor
import re, unicodedata, html
def key(s):
    s = html.unescape(s or '')
    s = re.sub(r'(?i)\s*oferta!?', ' ', s)
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'\s*-\s*(variante|\.)\s*$', '', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()
def num(s): return float(str(s).replace('.', '').replace(',', '.'))
def egg_box(text):
    """Precio de la caja cerrada de huevos leído de la descripción de Río Maipo."""
    t = html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))
    m = re.search(r'caja de (\d+) (?:huevos|unidades)? ?a \$ ?([\d\.]+)', t, re.I) or re.search(r'\$ ?([\d\.]+) caja de (\d+)', t, re.I)
    if not m: return None
    a, b = m.groups()
    return (int(a), num(b)) if re.search(r'caja de (\d+) (?:huevos|unidades)? ?a', m.group(0), re.I) else (int(b), num(a))
