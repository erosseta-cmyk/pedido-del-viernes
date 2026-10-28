"""Actualización semanal del catálogo Pedido del Viernes.

Lee los precios actuales de las tres distribuidoras, mueve cada precio de venta en el
mismo porcentaje que cambió su precio de compra y vuelve a generar index.html.

Frenos de seguridad:
  - Si una distribuidora no responde o se reconocen menos del 85 % de sus productos,
    sus precios quedan como estaban.
  - Si un precio de compra cambia más de un 25 % de una semana a otra, no se toca y
    queda marcado para revisión.
  - Un producto agotado o que ya no aparece se oculta; vuelve solo cuando reaparece.
  - La comparación con supermercado deja de mostrarse 28 días después de tomada.

Uso:  python build/update.py            (actualiza y genera)
      python build/update.py --render   (solo genera index.html con los datos actuales)
      python build/update.py --dump     (descarga y guarda lo leído, sin cambiar nada)
"""
import json, math, os, re, subprocess, sys, time, datetime, html, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from common import key, num, egg_box

B = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(B)
CAT = os.path.join(B, 'catalog.json')
BASE_ENC = os.path.join(B, 'base.enc')
ALIAS = os.path.join(B, 'artico_alias.json')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
      'Accept-Language': 'es-CL,es;q=0.9'}
MIN_FOUND, MAX_JUMP, CMP_DAYS = 0.85, 0.25, 28
NAMES = {'A': 'Ártico Congelados', 'R': 'Río Maipo', 'P': 'El Palomo'}


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f'{url}: {last}')


# ---------- lectura de proveedores ----------
def fetch_R():
    out = {}
    for page in range(1, 15):
        data = json.loads(get(f'https://riomaipo.cl/wp-json/wc/store/v1/products?per_page=100&page={page}'))
        if not data:
            break
        for p in data:
            pr = p.get('prices') or {}
            mu = int(pr.get('currency_minor_unit') or 0)
            price = float(pr.get('price') or 0) / (10 ** mu)
            out[key(p.get('name'))] = dict(price=price, sd=(p.get('short_description') or '') + ' ' + (p.get('description') or ''),
                                          stock=bool(p.get('is_in_stock', True)), raw=p.get('name'))
        if len(data) < 100:
            break
    return out


def fetch_P():
    out = {}
    for page in range(1, 20):
        data = json.loads(get(f'https://elpalomo.cl/products.json?limit=250&page={page}')).get('products', [])
        if not data:
            break
        for p in data:
            vs = p.get('variants') or [{}]
            v = vs[0]
            out[key(p.get('title'))] = dict(price=float(v.get('price') or 0), stock=any(x.get('available', True) for x in vs), raw=p.get('title'))
    return out


def fetch_A():
    """Lista oficial de Ártico: se pasa la página a líneas de texto y se buscan pares nombre/precio."""
    page = get('https://articocongelados.cl/Lista-de-Precio')
    t = re.sub(r'(?is)<(script|style).*?</\1>', ' ', page)
    t = re.sub(r'(?i)<\s*(br|/tr|/p|/div|/li|/h\d|/td|/th)[^>]*>', '\n', t)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
    lines = [re.sub(r'\s+', ' ', l).strip() for l in t.split('\n')]
    lines = [l for l in lines if l]
    out = {}
    for i, l in enumerate(lines):
        m = re.search(r'\$\s?([\d]{1,3}(?:\.\d{3})+|\d{3,6})(?!.*\$)', l)
        if not m:
            continue
        name = l[:m.start()].strip(' -:|$')
        if len(key(name)) < 4 and i > 0:  # precio en su propia línea: el nombre está en la anterior
            name = lines[i - 1]
        if len(key(name)) >= 4:
            out[key(name)] = dict(price=num(m.group(1)), stock=True, raw=name)
    return out, page


# ---------- base cifrada (precios de compra de la semana anterior) ----------
def crypt(data, enc):
    keyv = os.environ.get('BASE_KEY')
    if not keyv:
        raise SystemExit('Falta el secreto BASE_KEY')
    args = ['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000', '-a', '-A', '-pass', 'env:BASE_KEY'] + ([] if enc else ['-d'])
    r = subprocess.run(args, input=data, capture_output=True, check=True)
    return r.stdout


def load_base():
    return json.loads(crypt(open(BASE_ENC, 'rb').read(), False))


def save_base(b):
    open(BASE_ENC, 'wb').write(crypt(json.dumps(b, separators=(',', ':')).encode(), True))


# ---------- precio ----------
def round90(x):
    if x < 1000:
        return int(math.ceil(x / 10) * 10)
    return int(math.ceil((x - 90) / 100) * 100 + 90)


def metric(item, found):
    """Precio de referencia del proveedor para este producto (para huevos, la caja cerrada)."""
    if item['kind'] == 'egg':
        b = egg_box(found.get('sd', ''))
        return b[1] if b else None
    return found['price'] or None


def lookup(item, src, alias):
    k = key(item['k'])
    if item['s'] == 'A':
        k = key(alias.get(item['k'], item['k']))
    return src.get(k)


# ---------- generar la página ----------
def render(cat):
    today = datetime.date.today()
    items, cmp_dates = [], set()
    for it in cat['items']:
        if not it['on']:
            continue
        c = it.get('cmp')
        if c and (today - datetime.date.fromisoformat(c['d'])).days <= CMP_DAYS:
            cmp_dates.add(c['d'])
            c = {'sup': c.get('sup'), 'txt': c['txt']} if c.get('sup') else {'txt': c['txt']}
        else:
            c = 0
        items.append([it['id'], it['cat'], it['sub'], it['n'], it['u'], it['pv'], c])
    on = {i[0] for i in items}
    data = {'items': items, 'feat': [f for f in cat['feat'] if f in on]}
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    fmt = lambda d: f'{d.day} de {meses[d.month - 1]} de {d.year}'
    upd = datetime.date.fromisoformat(cat['updated'])
    cmp_txt = ''
    if cmp_dates:
        ds = sorted(datetime.date.fromisoformat(x) for x in cmp_dates)
        cmp_txt = fmt(ds[-1])
    t = open(os.path.join(B, 'template.html'), encoding='utf-8').read()
    km = json.load(open(os.path.join(B, 'comunas.json'), encoding='utf-8'))
    t = (t.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
          .replace('__KM__', json.dumps(km, ensure_ascii=False, separators=(',', ':')))
          .replace('__UPDATED__', json.dumps(fmt(upd), ensure_ascii=False))
          .replace('__CMPDATE__', json.dumps(cmp_txt, ensure_ascii=False)))
    i = t.index('<header')
    page = ('<!doctype html>\n<html lang="es"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            '<meta name="robots" content="noindex">\n' + t[:i] + '</head>\n<body>\n' + t[i:] + '\n</body></html>\n')
    open(os.path.join(ROOT, 'index.html'), 'w', encoding='utf-8').write(page)
    return len(items)


# ---------- actualización ----------
def update(dump=False):
    cat = json.load(open(CAT, encoding='utf-8'))
    alias = json.load(open(ALIAS, encoding='utf-8')) if os.path.exists(ALIAS) else {}
    base = None if dump else load_base()
    src, fail = {}, {}
    for s, fn in (('R', fetch_R), ('P', fetch_P), ('A', fetch_A)):
        try:
            r = fn()
            if s == 'A':
                r, raw = r
                os.makedirs(os.path.join(ROOT, 'diag'), exist_ok=True)
                open(os.path.join(ROOT, 'diag', 'artico.html'), 'w', encoding='utf-8').write(raw)
            src[s] = r
        except Exception as e:  # noqa: BLE001
            fail[s] = f'no respondió ({str(e)[:150]})'
    os.makedirs(os.path.join(ROOT, 'diag'), exist_ok=True)
    if dump:
        json.dump({s: {k: v.get('raw') for k, v in d.items()} for s, d in src.items()},
                  open(os.path.join(ROOT, 'diag', 'leido.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # ¿cada proveedor se leyó bien?
    for s in 'ARP':
        if s in fail:
            continue
        mine = [it for it in cat['items'] if it['s'] == s]
        found = [it for it in mine if lookup(it, src[s], alias)]
        if mine and len(found) / len(mine) < MIN_FOUND:
            fail[s] = f'solo se reconocieron {len(found)} de {len(mine)} productos; la página pudo cambiar'
    if dump:
        res = {'fallas': fail, 'leidos': {s: len(d) for s, d in src.items()}, 'sin_encontrar': {}, 'muestra': {}}
        for s in 'ARP':
            if s in src:
                res['sin_encontrar'][s] = [it['k'] for it in cat['items'] if it['s'] == s and not lookup(it, src[s], alias)]
                res['muestra'][s] = [v.get('raw') for v in list(src[s].values())[:400]] if s == 'A' else [v.get('raw') for v in list(src[s].values())[:15]]
        json.dump(res, open(os.path.join(ROOT, 'diag', 'resumen.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(res['leidos']), fail)
        return
    changes, held, hidden, back = [], [], [], []
    for it in cat['items']:
        s = it['s']
        if s in fail:
            continue
        f = lookup(it, src[s], alias)
        if not f or not f.get('stock', True):
            if it['on']:
                it['on'] = False
                hidden.append(it)
            continue
        m1 = metric(it, f)
        if not m1:
            continue
        if not it['on']:
            it['on'] = True
            back.append(it)
        m0 = base.get(it['id'])
        if not m0:
            base[it['id']] = m1
            continue
        r = m1 / m0
        if abs(r - 1) < 0.01:
            continue
        if abs(r - 1) > MAX_JUMP:
            held.append((it, m0, m1))
            continue
        old = it['pv']
        it['pv'] = round90(old * r)
        base[it['id']] = m1
        if it['pv'] != old:
            changes.append((it, old, it['pv'], r))
    cat['updated'] = datetime.date.today().isoformat()
    json.dump(cat, open(CAT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    save_base(base)
    n = render(cat)
    # informe
    clp = lambda v: '$' + f'{int(v):,}'.replace(',', '.')
    L = [f'Productos visibles en el catálogo: **{n}**', '']
    if fail:
        L += ['## ⚠️ Distribuidoras que no se pudieron leer (sus precios quedaron igual)', ''] + [f'- {NAMES[s]}: {why}' for s, why in fail.items()] + ['']
    if held:
        L += ['## ⚠️ Cambios de más de 25 % que NO se aplicaron (revisa en la página del proveedor)', '',
              '| Producto | Proveedor | Tu precio actual | Cambio proveedor |', '|---|---|---|---|']
        L += [f"| {it['n']} ({it['u']}) | {NAMES[it['s']]} | {clp(it['pv'])} | {(b / a - 1) * 100:+.0f} % |" for it, a, b in held] + ['']
    if changes:
        L += ['## Precios de venta actualizados', '', '| Producto | Antes | Ahora | Cambio proveedor |', '|---|---|---|---|']
        L += [f"| {it['n']} ({it['u']}) | {clp(a)} | {clp(b)} | {(r - 1) * 100:+.1f} % |" for it, a, b, r in changes] + ['']
    if hidden:
        L += ['## Ocultos por agotados o retirados', ''] + [f"- {it['n']} ({it['u']}) — {NAMES[it['s']]}" for it in hidden] + ['']
    if back:
        L += ['## Volvieron a estar disponibles', ''] + [f"- {it['n']} ({it['u']})" for it in back] + ['']
    if not (fail or held or changes or hidden or back):
        L += ['Sin cambios esta semana.']
    rep = '\n'.join(L)
    open(os.path.join(ROOT, 'INFORME.md'), 'w', encoding='utf-8').write(f'# Actualización {cat["updated"]}\n\n' + rep + '\n')
    title = f"Precios {datetime.date.today():%d-%m}: {len(changes)} cambios" + (', revisar' if (fail or held) else '')
    print(title)
    gh_out = os.environ.get('GITHUB_OUTPUT')
    if gh_out:
        with open(gh_out, 'a') as fh:
            fh.write(f'title={title}\n')
            fh.write(f"notify={'1' if (fail or held or changes or hidden) else '0'}\n")


if __name__ == '__main__':
    if '--render' in sys.argv:
        print(render(json.load(open(CAT, encoding='utf-8'))), 'productos')
    else:
        update(dump='--dump' in sys.argv)
