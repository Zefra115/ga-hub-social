#!/usr/bin/env python3
"""Archive Deck Lab - pipeline dati settimanale.

Uso:
  python3 -I pipeline.py fetch --work DIR [--prev-bundle FILE] [--prev-imgidx FILE] [--glossary FILE]
      Scarica meta, champion, archetipi (head-to-head, consenso, liste vincenti), ultimo major,
      tutte le carte dell'Index e le immagini delle carte nuove. Scrive in DIR:
      bundle.json, imgidx.json, cards/sNN.webp e miniature cards/tNN.webp (solo fogli nuovi), weekly_input.json.
  python3 -I pipeline.py build --work DIR --template FILE --out FILE [--weekly FILE]
      Inserisce bundle.json (piu' il commento settimanale in markdown, se dato) nel template.

Fonti: grandarchivestats.com, fractalofin.site, api.gatcg.com (rete: questi host devono essere consentiti).
"""
import argparse, glob, html, json, os, re, subprocess, sys, time, urllib.parse, datetime

GAS = "https://grandarchivestats.com"
FOI = "https://fractalofin.site"
API = "https://api.gatcg.com"
MIN_DECKS = 20


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, path=None, tries=6, min_size=0, pause=1.2):
    """Scarica con curl (usa il proxy dell'ambiente). Ritenta se il sito e' sovraccarico."""
    for t in range(tries):
        r = subprocess.run(["curl", "-sS", "-m", "90", "-L", url], capture_output=True)
        body = r.stdout
        ok = r.returncode == 0 and len(body) > min_size and b"under heavy load" not in body
        if ok:
            if path:
                open(path, "wb").write(body)
            time.sleep(pause)
            return body.decode("utf-8", "replace")
        log(f"  retry {t+1} {url} ({r.returncode}, {len(body)} bytes)")
        time.sleep(5 + t * 5)
    raise RuntimeError(f"download fallito: {url}")


def text(h):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t)))
    return re.sub(r"(\s*\|\s*)+", " | ", t)


# ---------------------------------------------------------------- meta
def fetch_meta():
    h = get(GAS + "/meta", min_size=50000)
    t = text(h)
    m = re.search(r"Current season · ([^·|]+?) · (\d+) events · (\d+) decks · (\d+) non-mirror matches", t)
    if m:
        snap = dict(season=m.group(1).strip(), events=int(m.group(2)), decks=int(m.group(3)), matches=int(m.group(4)),
                    date=datetime.date.today().isoformat())
    else:  # layout 2026-11: "The | <season> | meta | 10,147 | decks | 25,143 | matches | 481 | events"
        m = re.search(r"\| The \| ([^|]+?) \| meta \| ([\d,]+) \| decks \| ([\d,]+) \| matches \| ([\d,]+) \| events", t)
        num = lambda x: int(x.replace(",", ""))
        snap = dict(season=m.group(1).strip(), events=num(m.group(4)), decks=num(m.group(2)), matches=num(m.group(3)),
                    date=datetime.date.today().isoformat())
    cm = re.search(r"\| ([A-Z]{3}) \| " + re.escape(snap["season"]) + r" \|", t)
    snap["code"] = cm.group(1) if cm else SEASON_CODES.get(snap["season"], "")
    rows = []
    for r in re.finditer(r"\| (\d+) \| ([A-Z][^|]+?) \| (Tier \d) \| (\d+) \| ([\d.]+)% \| (\d+)-(\d+)-(\d+) \| ([\d.]+)% \| ([\d.]+)%", t):
        rows.append(dict(n=r.group(2).strip(), tier=r.group(3), decks=int(r.group(4)), share=float(r.group(5)),
                         wr=float(r.group(9)), adj=float(r.group(10))))
    if not rows:  # layout 2026-11: schede <li data-archetype ... data-tier ...>
        for li in re.finditer(r'<li\s+data-archetype="[^"]*"\s+data-decks="(\d+)"\s+data-tier="(\d)"\s+data-share="([\d.]+)"\s+data-wr="([\d.]+)"\s+data-ev="([\d.]+)"[^>]*?title="([^"]*)"[^>]*>\s*<a href="/meta/archetypes/([^"]+)"', h):
            dk = int(li.group(1))
            if dk < 10:
                continue
            am = re.search(r"adjusted win rate ([\d.]+)%", li.group(6))
            name = urllib.parse.unquote(html.unescape(li.group(7))).strip()
            rows.append(dict(n=name, tier="Tier " + li.group(2), decks=dk, share=round(float(li.group(3)), 1),
                             wr=round(float(li.group(4)), 1), adj=float(am.group(1)) if am else round(float(li.group(5)), 1)))
        rows.sort(key=lambda r: -r["decks"])
    mv = []
    seg = t[t.find("Meta movers"):t.find("Archetype breakdown")]
    if "Meta movers" not in t and "| Rising |" in t:
        seg = t[t.find("| Rising |"):t.find("| All time |")].replace("| Rising |", "| Gaining |").replace("| Falling |", "| Losing |")
    for side in ("Gaining", "Losing"):
        part = seg[seg.find(side):] if side == "Losing" else seg[seg.find("Gaining"):seg.find("Losing")]
        for r in re.finditer(r"\| ([A-Z][^|]+?) \| ([\d.]+)% -> ([\d.]+)% \| ([+\-−][\d.]+)", part):
            mv.append([r.group(1).strip(), float(r.group(4).replace("−", "-")), float(r.group(2)), float(r.group(3))])
    snap["trend"] = mv
    log(f"meta: {snap} · {len(rows)} archetipi")
    return snap, rows


def fetch_champions():
    h = get(GAS + "/champions", min_size=20000)
    slugs = sorted(set(re.findall(r'href="/champions\?c=([a-z0-9-]+)"', h)))
    out = []
    for s in slugs:
        h = get(f"{GAS}/champions?c={s}", min_size=20000)
        t = text(h)
        head = re.search(r"Champion Archive \| ([^|]+) \| ([^|]+?) · [^|]+ \| ([\d,]+) \| Decks Tracked \| ([\d.]+)% \| Win Rate", t) \
            or re.search(r"\| ([^|]+?) \| ([^|]+?) \| · [^|]+? season \| ([\d,]+) \| decks tracked \| ([\d.]+)% \| win rate", t)
        if not head:
            log("  champion non leggibile", s)
            continue
        seg = t[t.find("Decks Played"):]
        rows = re.findall(r"\| (\d+) \| ([A-Z][^|]+?) \| (\d+) \| (\d+)% \| ([\d.]+)%", seg)
        if not rows:  # layout 2026-11
            seg = t[t.find("Decks played"):]
            rows = re.findall(r"\| (\d+) \| ([A-Z][^|]+?) \| (\d+) \| decks \| (\d+)% \| of [^|]+ decks \| ([\d.]+)% \| win rate", seg)
        links = [urllib.parse.unquote(html.unescape(l)) for l in re.findall(r'href="/meta/archetypes/([^"?]+)\?champion=', h)]
        out.append(dict(name=head.group(1).strip(), slug=s, cls=head.group(2).strip(), decks=int(head.group(3).replace(",", "")),
                        wr=float(head.group(4)),
                        rows=[[r[1].strip(), links[i] if i < len(links) else None, int(r[2]), int(r[3]), float(r[4])] for i, r in enumerate(rows)]))
    out.sort(key=lambda c: -c["decks"])
    log(f"champion: {len(out)}")
    return out


def parse_archetype(h):
    t = text(h)

    def sec(a, b):
        s = t.find(a)
        return t[s:t.find(b, s + 5)] if s >= 0 else ""
    pm = lambda s: [[m.group(1).strip(), float(m.group(2)), float(m.group(3))] for m in re.finditer(r"\| ([^|]+?) \| In \| ([\d.]+)% \| WR \| ([\d.]+)%", s)]
    pa = lambda s: [[m.group(1).strip(), float(m.group(2)), float(m.group(3)), float(m.group(4))] for m in re.finditer(r"\| ([^|]+?) \| In \| ([\d.]+)% \| Avg \| ([\d.]+)× \| WR \| ([\d.]+)%", s)]
    mat, main, side = sec("| Material Deck | ·", "| Main Deck | ·"), sec("| Main Deck | ·", "| Sideboard | ·"), sec("| Sideboard | ·", "Recent placements")
    if not (pm(mat) or pa(main)) and "| Material Deck |" in t:  # layout 2026-11
        def sec2(a, b):
            s = t.find(a)
            e = t.find(b, s + 5) if s >= 0 else -1
            return t[s:e if e > 0 else s + 20000] if s >= 0 else ""
        mat2, main2 = sec2("| Material Deck |", "| Main Deck |"), sec2("| Main Deck |", "| Sideboard |")
        side2 = sec2("| Sideboard |", " matches |")
        pm2 = lambda s: [[m.group(2).strip(), float(m.group(1)), float(m.group(3))] for m in re.finditer(r"\| ([\d.]+)% \| ([^|]+?) \| ([\d.]+)% \| win rate", s)]
        pa2 = lambda s: [[m.group(3).strip(), float(m.group(1)), float(m.group(2)), float(m.group(4))] for m in re.finditer(r"\| ([\d.]+)% \| ([\d.]+)× \| ([^|]+?) \| ([\d.]+)% \| win rate", s)]
        pm, pa, mat, main, side = pm2, pa2, mat2, main2, side2
    h2h = {}
    k = t.find("ELO Δ/match |")
    if k >= 0:
        for m in re.finditer(r"\| ([A-Z][^|]+?) \| ([\d.]+)% \| (\d+) \| (\d+)-(\d+)-(\d+) \| ([\d.]+)% \| ([\d.]+)% \| ([\d.]+)% \| ([+\-−]?[\d.]+)", t[k:]):
            h2h[m.group(1).strip()] = [int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))]
    best = None
    for li in re.findall(r'<li class="rp-row">(.*?)</li>', h, re.S):
        g = lambda p: (re.search(p, li, re.S) or [None, None])[1]
        try:
            rank = int(re.sub(r"\D", "", g(r'rp-ord">(.*?)<')))
            size = int(re.sub(r"\D", "", g(r'rp-of">(.*?)<')))
        except Exception:
            continue
        cat = g(r'cat-tag[^"]*">(.*?)<') or ""
        score = (rank == 1) * 1000 + {"Ascent": 400, "Nationals": 450, "Worlds": 500, "Regionals": 300, "Online League": 100}.get(cat, 0) + size - rank * 8
        d = dict(date=g(r'rp-date">(.*?)<'), rank=rank, size=size, event=html.unescape(g(r'rp-event-name"[^>]*>(.*?)<') or ""), cat=cat,
                 player=html.unescape(g(r'rp-player"[^>]*>(.*?)<') or ""), record=g(r'rp-record"[^>]*>(.*?)<'),
                 url=g(r'href="(/events/\d+/decks/\d+)"'), score=score)
        if best is None or score > best["score"]:
            best = d
    return dict(material=pm(mat), main=pa(main), side=pa(side), best=best, h2h=h2h)


def fetch_archetypes(names):
    out = {}
    for i, n in enumerate(names, 1):
        h = get(f"{GAS}/meta/archetypes/{urllib.parse.quote(n)}", min_size=20000)
        a = parse_archetype(h)
        if a["best"] and a["best"]["url"]:
            dh = get(GAS + a["best"]["url"], min_size=5000)
            m = re.search(r"<textarea[^>]*>(.*?)</textarea>", dh, re.S)
            a["best"]["list"] = html.unescape(m.group(1)).strip() if m else ""
            a["best"].pop("score", None)
        out[n] = a
        log(f"  [{i}/{len(names)}] {n}: main {len(a['main'])}, h2h {len(a['h2h'])}")
    return out


def fetch_major():
    h = get(FOI + "/", min_size=20000)
    for m in re.finditer(r'<a class="evt ([a-z]+)" href="([^"]+)" data-decklists="(\d+)"[^>]*>(.*?)</a>', h, re.S):
        cat, href, ndl, inner = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if cat not in ("ascent", "nationals", "worlds") or ndl < 8:
            continue
        name = html.unescape(re.search(r"<h3>(.*?)</h3>", inner).group(1)).strip()
        if re.search(r"team|3v3|triple|draft|sealed", name, re.I):
            continue
        date = re.search(r'date_loc">\s*([\d-]+)', inner).group(1)
        players = int(re.search(r"(\d+) entrants", inner).group(1))
        eh = get(FOI + href, min_size=50000)
        tc = eh[eh.find("Single Elimination Top Cut"):]
        tc = tc[:tc.find("</table>")]
        top = []
        for row in re.findall(r'<tr class="p-row[^"]*">(.*?)</tr>', tc, re.S):
            rank = int(re.search(r'p_rank">(\d+)', row).group(1))
            player = html.unescape(re.search(r'playername[^>]*><a[^>]*>(.*?)</a>', row).group(1)).split(" #")[0]
            rec = re.search(r'p_record">([\d-]+)', row).group(1)
            did = re.search(r'href="#(deck_\d+)"', row).group(1)
            deckname = html.unescape(re.search(r'href="#deck_\d+"[^>]*>(.*?)</a>', row).group(1)).strip()
            s = eh.find(f'<div class="decklist collapse" id="{did}"')
            blk = eh[s:eh.find('<div class="decklist collapse"', s + 10)]
            lm = re.search(r'<textarea class="omniexport">(.*?)</textarea>', blk, re.S)
            top.append(dict(rank=rank, player=player, record=rec, deck=deckname, list=html.unescape(lm.group(1)).strip() if lm else ""))
        top.sort(key=lambda x: x["rank"])
        log(f"major: {name} {date} {players} giocatori, top {len(top)}")
        return dict(name=name, date=date, players=players, url=FOI + href, top=top[:8])
    return None


# ---------------------------------------------------------------- eventi (per i periodi 30/15 giorni)
RES = {"win": "W", "loss": "L", "draw": "D", "intentional": "I", "bye": "B"}


def parse_event(h):
    t = text(h[:200000])
    head = re.search(r"Event Archive \| ([^|]+) \| ([\d-]+) · Season ([^·|]+) · ([^·|]+) · (\d+) players", t)
    pl = []
    for row in re.split(r'<div class="placement-row', h)[1:]:
        g = lambda p: (re.search(p, row, re.S) or [None, None])[1]
        try:
            rank = int(g(r'placement-rank[^>]*><b>(\d+)</b>'))
        except Exception:
            continue
        name = html.unescape(g(r'placement-name">(.*?)<') or "").strip()
        arch = html.unescape(g(r'placement-deck-name">(.*?)<') or "").strip()
        deck = g(r'class="placement-deck" href="([^"]+)"')
        ms = []
        for li in re.findall(r'<li class="pl-round">(.*?)</li>', row, re.S):
            tag = re.search(r"round-tag-([a-z]+)", li)
            opp = re.search(r'pl-round-opp-arch[^"]*"[^>]*>(.*?)</a>', li, re.S)
            if tag:
                ms.append([RES.get(tag.group(1), "?"), html.unescape(opp.group(1)).strip() if opp else ""])
        pl.append([rank, name, arch, deck, ms])
    return dict(name=head.group(1).strip() if head else "", date=head.group(2) if head else "", fmt=head.group(4).strip() if head else "", players=pl)


def fetch_events(days, cache, today):
    """Eventi della stagione negli ultimi `days` giorni, con tutti i match. Riusa la cache per gli eventi gia' letti."""
    h = get(GAS + "/", min_size=50000)
    t0 = datetime.date.fromisoformat(today)
    rows = re.findall(r'<tr data-event-id="(\d+)"[^>]*>\s*<td>([\d-]+)</td>\s*<td><a href="/events/\d+">(.*?)</a></td>.*?cat-tag-([a-z-]+)".*?<td class="num">(\d+)</td>', h, re.S)
    if not rows:  # layout 2026-11: <section class="hm-day"> con <b>Nov 22</b> e <li class="hm-row">
        for sec in re.split(r'<section class="hm-day">', h)[1:]:
            dm = re.search(r'hm-dayhead">\s*<b>([A-Z][a-z]{2}) (\d+)</b>', sec)
            if not dm:
                continue
            d = datetime.datetime.strptime(f"{dm.group(1)} {dm.group(2)} {t0.year}", "%b %d %Y").date()
            if d > t0:
                d = d.replace(year=t0.year - 1)
            for li in re.findall(r'<li class="hm-row"(.*?)</li>', sec, re.S):
                g = lambda p: (re.search(p, li, re.S) or [None, None])[1]
                eid, name, cat, size = g(r'data-event-id="(\d+)"'), g(r'class="hm-name"[^>]*>(.*?)</a>'), g(r'data-cat="([a-z-]+)"'), g(r'hm-pl"><b>(\d+)</b>')
                if eid and name and size:
                    rows.append((eid, d.isoformat(), name, cat or "", size))
    out = {}
    for eid, date, name, cat, size in rows:
        age = (t0 - datetime.date.fromisoformat(date)).days
        if age > days:
            continue
        c = cache.get(eid)
        if c and age > 3 and c.get("players"):
            out[eid] = c
            continue
        try:
            e = parse_event(get(f"{GAS}/events/{eid}", min_size=5000, pause=0.8))
        except Exception as ex:
            log("  evento non leggibile", eid, ex)
            if c:
                out[eid] = c
            continue
        e.update(id=eid, date=date, name=html.unescape(name).strip(), cat=cat, size=int(size))
        out[eid] = e
    log(f"eventi: {len(out)} negli ultimi {days} giorni ({sum(1 for k in out if k not in cache)} nuovi)")
    return out


def window_stats(events, days, today, universe):
    t0 = datetime.date.fromisoformat(today)
    ev = [e for e in events.values() if (t0 - datetime.date.fromisoformat(e["date"])).days <= days and e.get("fmt", "Standard").lower().startswith("standard")]
    decks, rec, h2h = {}, {}, {}
    nm = 0
    for e in ev:
        for rank, name, arch, deck, ms in e["players"]:
            if not arch:
                continue
            decks[arch] = decks.get(arch, 0) + 1
            for r, opp in ms:
                if r not in "WLD" or not opp or opp == arch:
                    continue
                nm += 1
                a = rec.setdefault(arch, [0, 0, 0])
                a["WLD".index(r)] += 1
                hh = h2h.setdefault(arch, {}).setdefault(opp, [0, 0, 0])
                hh["WLD".index(r)] += 1
    tot = sum(decks.values()) or 1
    meta = {}
    for a, n in decks.items():
        w, l, d = rec.get(a, [0, 0, 0])
        m = w + l + d
        meta[a] = [n, round(100 * n / tot, 1), round(100 * w / m, 1) if m else None, m]
    H = {}
    for a, opps in h2h.items():
        if a not in universe:
            continue
        for b, (w, l, d) in opps.items():
            m = w + l + d
            if b in universe and m >= 3:
                H.setdefault(a, {})[b] = [m, w, l, d, round(100 * w / m, 1), round(100 * (w + 0.5 * d + 5) / (m + 10), 1)]
    dates = sorted(e["date"] for e in ev)
    return dict(days=days, events=len(ev), decks=tot, matches=nm // 2, players=sum(e["size"] for e in ev),
                start=dates[0] if dates else None, end=dates[-1] if dates else None, meta=meta, h2h=H)


def week_event(events, today, days=7):
    t0 = datetime.date.fromisoformat(today)
    W = {"worlds": 5, "nationals": 4, "ascent": 3, "regionals": 2}
    ev = [e for e in events.values() if (t0 - datetime.date.fromisoformat(e["date"])).days <= days and e["players"]]
    if not ev:
        return None
    e = max(ev, key=lambda e: (e["size"], W.get(e["cat"], 0)))
    top = sorted([p for p in e["players"] if p[0] <= 8], key=lambda p: p[0])[:8]
    return dict(id=e["id"], name=e["name"], date=e["date"], cat=e["cat"], players=e["size"], url=f"{GAS}/events/{e['id']}",
                top=[[p[0], p[2], p[1]] for p in top])


def pick_featured_events(events, today, history, max_age=7):
    """Lista della settimana: archetipo diverso dalle ultime 6 settimane; prima i vincitori degli eventi piu' grandi, poi i secondi posti..."""
    t0 = datetime.date.fromisoformat(today)
    recent = {h["arch"] for h in (history or [])[-6:]}
    W = {"worlds": 5000, "nationals": 4000, "ascent": 3000, "regionals": 2000}
    for age in (max_age, 14, 31):
        ev = [e for e in events.values() if (t0 - datetime.date.fromisoformat(e["date"])).days <= age and e["players"] and e["size"] >= 8]
        cands = []
        for e in ev:
            for p in e["players"]:
                if p[0] <= 4 and p[2] and p[3] and p[2] not in recent:
                    cands.append((p[0], -(W.get(e["cat"], 0) + e["size"]), e, p))
        cands.sort(key=lambda c: (c[0], c[1]))
        for rank, _, e, p in cands[:12]:
            try:
                dh = get(GAS + p[3], min_size=5000)
                m = re.search(r"<textarea[^>]*>(.*?)</textarea>", dh, re.S)
                lst = html.unescape(m.group(1)).strip() if m else ""
            except Exception:
                lst = ""
            if "# Main Deck" in lst or "# main deck" in lst.lower():
                return dict(arch=p[2], player=p[1], event=e["name"], date=e["date"], size=e["size"], rank=rank, cat=e["cat"], list=lst, url=GAS + p[3])
    return None


# ---------------------------------------------------------------- carte
def fetch_cards(work):
    os.makedirs(f"{work}/api", exist_ok=True)
    first = json.loads(get(f"{API}/cards/search?page=1&page_size=50", min_size=1000, pause=0.2))
    pages = first["total_pages"]
    allc = first["data"]
    for p in range(2, pages + 1):
        allc += json.loads(get(f"{API}/cards/search?page={p}&page_size=50", min_size=1000, pause=0.2))["data"]
    log(f"carte: {len(allc)} da {pages} pagine")
    return allc


def build_images(work, cards, prev_idx):
    """Aggiunge fogli immagine solo per le carte nuove (i fogli esistenti restano invariati)."""
    from PIL import Image
    idx = dict(prev_idx or {})
    imgs = {}
    for c in cards:
        eds = c["editions"]
        d = [e for e in eds if e["uuid"] == c.get("default_edition")] or [e for e in eds if e.get("is_default")] or eds
        if d and d[0].get("image"):
            imgs.setdefault(c["name"], d[0]["image"])
    json.dump(imgs, open(f"{work}/imgmap.json", "w"))
    new = sorted(n for n in imgs if n not in idx)
    if not new:
        log("immagini: nessuna carta nuova")
        return idx, []
    next_sheet = (max(v[0] for v in idx.values()) + 1) if idx else 0
    os.makedirs(f"{work}/raw", exist_ok=True)
    os.makedirs(f"{work}/cards", exist_ok=True)
    W, H, C, PER = 300, 420, 10, 100
    written = []
    for k in range(0, len(new), PER):
        chunk = new[k:k + PER]
        s = next_sheet + k // PER
        rows = (len(chunk) + C - 1) // C
        sheet = Image.new("RGB", (W * C, H * rows), (20, 22, 30))
        for i, n in enumerate(chunk):
            p = f"{work}/raw/" + imgs[n].split("/")[-1]
            try:
                if not os.path.exists(p):
                    get(API + imgs[n], p, min_size=1000, pause=0.1)
                im = Image.open(p).convert("RGB")
                if im.width > im.height:
                    im = im.rotate(90, expand=True)
                im.thumbnail((W, H), Image.LANCZOS)
                cell = Image.new("RGB", (W, H), (20, 22, 30))
                cell.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
                sheet.paste(cell, ((i % C) * W, (i // C) * H))
                idx[n] = [s, i]
            except Exception as e:
                log("  immagine non disponibile", n, e)
        f = f"cards/s{s:02d}.webp"
        sheet.save(f"{work}/{f}", "WEBP", quality=70, method=6)
        written.append(f)
        written.append(make_thumb(work, s, sheet))
    log(f"immagini: {len(new)} carte nuove in {written}")
    return idx, written


THUMB = 0.4  # miniature per la griglia dell'app: 120x168 per carta


def make_thumb(work, s, sheet=None):
    """Foglio di miniature cards/tNN.webp (stessa disposizione di sNN, 40%): la griglia dell'app pesa ~15 volte meno."""
    from PIL import Image
    sheet = sheet or Image.open(f"{work}/cards/s{s:02d}.webp").convert("RGB")
    t = sheet.resize((round(sheet.width * THUMB), round(sheet.height * THUMB)), Image.LANCZOS)
    f = f"cards/t{s:02d}.webp"
    t.save(f"{work}/{f}", "WEBP", quality=62, method=6)
    return f


def cmd_thumbs(a):
    """Rigenera tutte le miniature dai fogli cards/sNN.webp presenti in --work."""
    out = []
    for n in sorted(os.listdir(f"{a.work}/cards")):
        m = re.fullmatch(r"s(\d+)\.webp", n)
        if m:
            out.append(make_thumb(a.work, int(m.group(1))))
    log(f"miniature: {len(out)} fogli")
    print(json.dumps(out))


def card_rows(cards, idx, sheets_count, glossary, cons):
    """Riga compatta per carta + base di conoscenza (parole chiave e uso negli archetipi)."""
    kw_names = []
    for name, g in glossary.items():
        if g["kind"] != "keyword":
            continue
        base = re.sub(r" N\+?$| N$", "", name.split("/")[0].split(" (")[0]).strip()
        kw_names.append((name, re.compile(r"\b" + re.escape(base) + r"\b")))
    TERMS = ["Glimpse", "Recover", "Suppress", "Negate", "Sacrifice", "Summon", "Gather", "Load", "Scavenge N", "Ephemeral", "Distant",
             "Enlighten Counters", "Preparation Counters", "Buff Counters", "Level Counters", "Banish", "Reserve", "Influence", "Transform", "Obedience", "Fostered"]
    term_res = [(t, re.compile(r"\b" + re.escape(re.sub(r" N$| Counters$", "", t)) + r"s?\b", re.I)) for t in TERMS if t in glossary]
    usage = {}
    for an, a in cons.items():
        for zone, lst in (("M", a["main"]), ("S", a["side"]), ("R", a["material"])):
            for r in lst:
                if r[1] >= 10:
                    usage.setdefault(r[0], []).append([an, zone, round(r[1]), r[2] if zone != "R" else 1])
    rows, seen = [], set()
    gl_keys = list(glossary.keys())
    for c in cards:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        fx = (c["effect_raw"] or "").strip()
        lim = (c.get("legality") or {}).get("STANDARD", {}).get("limit") if c.get("legality") else None
        kws = sorted({gl_keys.index(n) for n, rx in kw_names if rx.search(fx)} | {gl_keys.index(n) for n, rx in term_res if rx.search(fx)})
        v = idx.get(c["name"])
        rows.append([c["name"], "/".join(c["types"]), "/".join(c["subtypes"] or []), "/".join(c["elements"] or []), c["cost_memory"], c["cost_reserve"],
                     c["level"], c["power"], c["life"], c["durability"], c.get("speed"), lim, fx, "/".join(c.get("classes") or []),
                     v[0] * 100 + v[1] if v else -1, c.get("slug") or "", kws, sorted(usage.get(c["name"], []), key=lambda u: -u[2])[:12]])
    return rows


def pick_featured(cons, meta, major, today):
    """Lista della settimana: vincitrice dell'evento piu' importante degli ultimi 9 giorni, altrimenti il vincitore dell'ultimo major."""
    t0 = datetime.date.fromisoformat(today)
    best = None
    for n, c in cons.items():
        b = c.get("best") or {}
        if not b.get("list") or b.get("rank") != 1 or not b.get("date"):
            continue
        try:
            age = (t0 - datetime.date.fromisoformat(b["date"])).days
        except Exception:
            continue
        if age > 9:
            continue
        score = {"Worlds": 5000, "Nationals": 4000, "Ascent": 3000, "Regionals": 2000, "Online League": 500}.get(b.get("cat"), 0) + b.get("size", 0)
        if best is None or score > best[0]:
            best = (score, dict(arch=n, player=b["player"], event=b["event"], date=b["date"], size=b["size"], rank=1, cat=b.get("cat"), record=b.get("record"), list=b["list"]))
    if best:
        return best[1]
    if major and major.get("top"):
        w = major["top"][0]
        return dict(arch=w["deck"], player=w["player"], event=major["name"], date=major["date"], size=major["players"], rank=1, cat="Major", record=w["record"], list=w["list"])
    return None


# ---------------------------------------------------------------- post instagram
BG, SURF, LINE, FG, MUTED, ACC, GOLD = (13, 15, 23), (23, 27, 40), (44, 51, 70), (236, 239, 246), (150, 158, 180), (157, 146, 255), (231, 189, 71)
GOOD, BAD = (91, 214, 154), (255, 131, 120)
ELC = {"Fire": (255, 122, 77), "Water": (98, 163, 255), "Wind": (95, 210, 126)}
SW, SH = 1080, 1350


def _font(w, size):
    import PIL.ImageFont as F
    names = {"black": ["InterDisplay-Black.otf", "InterDisplay-ExtraBold.otf", "Inter-Bold.otf"], "bold": ["InterDisplay-Bold.otf", "Inter-Bold.otf"],
             "semi": ["Inter-SemiBold.otf", "Inter-Medium.otf"], "reg": ["Inter-Regular.otf"]}[w]
    for n in names:
        for d in ("/usr/share/fonts/opentype/inter/", "/usr/share/fonts/truetype/inter/"):
            if os.path.exists(d + n):
                return F.truetype(d + n, size)
    return F.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if w != "reg" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


BRAND, HANDLE = "GA.HUB", "@ga_hub_it"
SEASON_CODES = {".asphodel/paradise": "PRD", "Radiant Origins": "RDO", "Phantom Monarchs": "PTM", "Abyssal Heaven": "HVN",
                "Alchemical Revolution": "ALC", "Distorted Reflections": "DTR", "Mercurial Heart": "MRC", "Mortal Ambition": "AMB"}
LOGO = None


def load_season_logo(work, snap):
    """Logo dell'espansione della stagione (fractalofin.site/static/season/<CODICE>.png), messo in cache nella cartella di lavoro."""
    global LOGO
    from PIL import Image
    code = snap.get("code") or SEASON_CODES.get(snap.get("season", ""), "")
    if not code:
        log("logo stagione: codice sconosciuto per", snap.get("season"))
        return
    f = f"{work}/season-{code}.png"
    try:
        if not os.path.exists(f):
            get(f"{FOI}/static/season/{code}.png", f, min_size=1000, pause=0.2)
        im = Image.open(f).convert("RGBA")
        h = 88
        LOGO = im.resize((int(im.width * h / im.height), h), Image.LANCZOS)
        log(f"logo stagione {code}: {LOGO.size}")
    except Exception as e:
        log("logo stagione non disponibile", code, e)
        LOGO = None


def _base(n, tot, kicker, title, top=0, tsize=64):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(im)
    for y in range(0, 420 + top):  # alone viola in alto
        a = max(0, 1 - y / (420 + top))
        d.line([(0, y), (SW, y)], fill=tuple(int(BG[i] + (ACC[i] - BG[i]) * 0.16 * a) for i in range(3)))
    d.rounded_rectangle([64, top + 62, 64 + 50, top + 62 + 50], 13, fill=ACC)
    d.text((89, top + 87), "GA", font=_font("black", 21), fill=BG, anchor="mm")
    d.text((130, top + 64), BRAND, font=_font("black", 24), fill=FG)
    d.text((130, top + 92), f"{HANDLE} · Grand Archive TCG", font=_font("reg", 18), fill=MUTED)
    right = SW - 64
    if LOGO is not None:
        im.paste(LOGO, (right - LOGO.width, top + 42), LOGO)
        right -= LOGO.width + 18
    if n:
        d.text((right, top + 76), f"{n}/{tot}", font=_font("semi", 22), fill=MUTED, anchor="ra")
    y = top + 160
    if kicker:
        d.text((64, y), kicker.upper(), font=_font("semi", 24), fill=ACC)
        y += 40
    if title:
        f = _font("black", tsize)
        for line in _wrap(d, title, f, SW - 128):
            d.text((64, y), line, font=f, fill=FG)
            y += int(tsize * 1.16)
    return im, d, y + 16


def _wrap(d, s, f, w):
    out, cur = [], ""
    for word in s.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) <= w:
            cur = t
        else:
            out.append(cur)
            cur = word
    return out + ([cur] if cur else [])


def _footer(d, txt="Data: grandarchivestats.com · Official card index gatcg.com", bottom=0):
    d.line([(64, SH - bottom - 92), (SW - 64, SH - bottom - 92)], fill=LINE, width=2)
    d.text((64, SH - bottom - 70), txt, font=_font("reg", 19), fill=MUTED)
    d.text((SW - 64, SH - bottom - 70), HANDLE, font=_font("bold", 20), fill=ACC, anchor="ra")


def _ord(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _dot(d, x, y, name, r=9):
    col = next((v for k, v in ELC.items() if name.startswith(k)), (166, 173, 191))
    d.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _card_img(work, name, imgmap):
    from PIL import Image
    p = imgmap.get(name)
    if not p:
        return None
    f = f"{work}/raw/" + p.split("/")[-1]
    try:
        if not os.path.exists(f):
            os.makedirs(f"{work}/raw", exist_ok=True)
            get(API + p, f, min_size=1000, pause=0.1)
        im = Image.open(f).convert("RGB")
        return im.rotate(90, expand=True) if im.width > im.height else im
    except Exception as e:
        log("  immagine mancante", name, e)
        return None


def _grid(im, d, work, imgmap, cards, x0, y0, w, cols, qty=True, gap=14):
    from PIL import Image, ImageDraw
    cw = (w - gap * (cols - 1)) // cols
    ch = int(cw * 1.4)
    for i, (q, n) in enumerate(cards):
        x, y = x0 + (i % cols) * (cw + gap), y0 + (i // cols) * (ch + gap)
        c = _card_img(work, n, imgmap)
        if c:
            c = c.resize((cw, ch), Image.LANCZOS)
            m = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, cw - 1, ch - 1], max(6, cw // 18), fill=255)
            im.paste(c, (x, y), m)
        else:
            d.rounded_rectangle([x, y, x + cw, y + ch], 10, fill=SURF, outline=LINE)
            f = _font("semi", 16)
            yy = y + 16
            for line in _wrap(d, n, f, cw - 20)[:5]:
                d.text((x + 10, yy), line, font=f, fill=FG)
                yy += 22
        if qty and q > 1:
            bx, by, r = x + cw - 8, y + ch - 8, 22
            d.ellipse([bx - 2 * r, by - 2 * r, bx, by], fill=GOLD, outline=BG, width=3)
            d.text((bx - r, by - r), f"{q}", font=_font("black", 24), fill=BG, anchor="mm")
    rows = (len(cards) + cols - 1) // cols
    return y0 + rows * (ch + gap) - gap


def _parse(lst):
    out, sec = {"material": [], "main": [], "side": []}, "main"
    for l in (lst or "").splitlines():
        l = l.strip()
        if not l:
            continue
        if l.startswith("#"):
            sec = "material" if "material" in l.lower() else "side" if "side" in l.lower() else "main"
            continue
        m = re.match(r"(\d+)\s+(.+)", l)
        if m:
            out[sec].append((int(m.group(1)), m.group(2).strip()))
    return out


def _fit_cols(n, avail_h, w, gap=12, start=4):
    cols = start
    while cols < 12:
        cw = (w - gap * (cols - 1)) // cols
        if ((n + cols - 1) // cols) * (int(cw * 1.4) + gap) - gap <= avail_h:
            return cols
        cols += 1
    return cols


def _grid_h(n, cols, w, gap=12):
    cw = (w - gap * (cols - 1)) // cols
    return ((n + cols - 1) // cols) * (int(cw * 1.4) + gap) - gap


def _grid_best(im, d, work, imgmap, cards, x0, y0, w, avail_h, qty=False, gap=14):
    """Sceglie il numero di colonne che rende le carte piu' grandi possibile, preferendo righe complete; griglia centrata."""
    from PIL import Image, ImageDraw
    n = len(cards)
    best = None
    for c in range(2, 9):
        rows = (n + c - 1) // c
        cw = min((w - gap * (c - 1)) / c, ((avail_h - gap * (rows - 1)) / rows) / 1.4)
        empty = rows * c - n
        score = cw - empty * 6
        if best is None or score > best[0]:
            best = (score, c, int(cw))
    _, c, cw = best
    gw = c * cw + gap * (c - 1)
    return _grid(im, d, work, imgmap, cards, x0 + (w - gw) // 2, y0, gw, c, qty=qty, gap=gap)


def make_stories(work, imgmap, snap, season, champ, rank, per, W30, W15, feat, de, issue):
    """Storie Instagram 1080x1920 (testi in inglese). Contenuto tra y=250 e y=1670 (zone libere dall'interfaccia di Instagram)."""
    global SW, SH
    old = (SW, SH)
    SW, SH = 1080, 1920
    TOP, BOT = 170, 200
    out = []
    try:
        # storia 1: teaser del meta
        im, d, y = _base(None, None, f"Week of {de}", f"Meta Report #{issue}", top=TOP, tsize=78)
        d.text((64, y), f"Season: {snap['season']}", font=_font("semi", 34), fill=GOLD)
        y += 64
        if W30:
            for i, (lab, val) in enumerate([("events", W30["events"]), ("players", W30["players"]), ("matches", W30["matches"])]):
                x = 64 + i * 330
                d.rounded_rectangle([x, y, x + 300, y + 116], 22, fill=SURF, outline=LINE, width=2)
                d.text((x + 26, y + 16), f"{val:,}".replace(",", "."), font=_font("black", 46), fill=FG)
                d.text((x + 26, y + 78), lab.upper(), font=_font("semi", 20), fill=MUTED)
            y += 150
        d.text((64, y), f"MOST PLAYED · {per.upper()}", font=_font("semi", 26), fill=ACC)
        y += 50
        for i, r in enumerate(rank[:3]):
            d.rounded_rectangle([64, y, SW - 64, y + 118], 24, fill=SURF, outline=LINE, width=2)
            d.text((104, y + 59), f"{i+1}", font=_font("black", 58), fill=GOLD, anchor="lm")
            _dot(d, 192, y + 42, r[0])
            f = _font("bold", 32)
            nm = r[0] if d.textlength(r[0], font=f) < 600 else r[0][:32] + "…"
            d.text((216, y + 24), nm, font=f, fill=FG)
            d.text((192, y + 72), f"{champ.get(r[0], '')} · WR {r[2]}%", font=_font("reg", 24), fill=MUTED)
            d.text((SW - 100, y + 59), f"{r[1]}%", font=_font("black", 46), fill=FG, anchor="rm")
            y += 132
        y += 18
        if W15 and W15["meta"]:
            mv = [[n, round(v[1] - season[n]["share"], 1), v[1]] for n, v in W15["meta"].items() if n in season and (v[1] >= 1 or season[n]["share"] >= 1)]
            up = sorted([m for m in mv if m[1] > 0], key=lambda m: -m[1])[:2]
            dn = sorted([m for m in mv if m[1] < 0], key=lambda m: m[1])[:2]
            for col, (lab, arr, c) in enumerate([("RISING ▲", up, GOOD), ("FALLING ▼", dn, BAD)]):
                x = 64 + col * 486
                d.text((x, y), lab, font=_font("semi", 24), fill=c)
                yy = y + 44
                for m in arr:
                    d.rounded_rectangle([x, yy, x + 466, yy + 100], 18, fill=SURF, outline=LINE, width=2)
                    _dot(d, x + 26, yy + 32, m[0], 7)
                    f = _font("bold", 22)
                    nm = m[0] if d.textlength(m[0], font=f) < 400 else m[0][:28] + "…"
                    d.text((x + 44, yy + 18), nm, font=f, fill=FG)
                    d.text((x + 26, yy + 58), f"{'+' if m[1] > 0 else ''}{m[1]} pts · now {m[2]}%", font=_font("reg", 22), fill=c)
                    yy += 114
            y += 44 + max(len(up), len(dn), 1) * 114
        cy = max(y + 16, SH - BOT - 92 - 150)
        d.rounded_rectangle([64, cy, SW - 64, cy + 124], 28, fill=ACC)
        d.text((SW // 2, cy + 44), "Full report + deck of the week", font=_font("black", 36), fill=BG, anchor="mm")
        d.text((SW // 2, cy + 90), "in our latest post", font=_font("semi", 28), fill=BG, anchor="mm")
        _footer(d, bottom=BOT)
        im.save(f"{work}/social/story-1.jpg", quality=92)
        out.append("story-1.jpg")
        # storia 2: lista della settimana
        if feat:
            L = _parse(feat["list"])
            pos = {1: "1st", 2: "2nd", 3: "3rd", 4: "Top 4"}.get(feat.get("rank", 1), "Top 8")
            im, d, y = _base(None, None, "Deck of the week", feat["arch"], top=TOP, tsize=72 if len(feat["arch"]) <= 22 else 58)
            f = _font("reg", 28)
            for line in _wrap(d, f"{feat['player']} · {pos} of {feat['size']} · {feat['event']}", f, SW - 128)[:2]:
                d.text((64, y - 6), line, font=f, fill=MUTED)
                y += 38
            y += 24
            d.text((64, y), f"MATERIAL DECK · {sum(q for q, _ in L['material'])}", font=_font("semi", 24), fill=ACC)
            y += 44
            cy = SH - BOT - 92 - 140
            keys = sorted([c for c in L["main"] if c[0] >= 4], key=lambda c: c[1])[:6] or sorted(L["main"], key=lambda c: -c[0])[:6]
            kh = _grid_h(len(keys), 6, SW - 128, 14)
            mat_h = cy - 40 - (kh + 44 + 30) - y
            y = _grid_best(im, d, work, imgmap, L["material"], 64, y, SW - 128, mat_h, qty=False, gap=14) + 30
            d.text((64, y), "KEY CARDS · 4 COPIES" if keys and keys[0][0] >= 4 else "KEY CARDS", font=_font("semi", 24), fill=ACC)
            _grid(im, d, work, imgmap, keys, 64, y + 44, SW - 128, 6, qty=True, gap=14)
            d.rounded_rectangle([64, cy, SW - 64, cy + 120], 28, fill=ACC)
            d.text((SW // 2, cy + 60), "Full decklist in our latest post", font=_font("black", 36), fill=BG, anchor="mm")
            _footer(d, "Card images © Weebs of the Shore", bottom=BOT)
            im.save(f"{work}/social/story-2.jpg", quality=92)
            out.append("story-2.jpg")
    finally:
        SW, SH = old
    return out


def cmd_social(a):
    work = a.work
    b = json.loads(open(f"{work}/bundle.json").read())
    imgmap = json.load(open(f"{work}/imgmap.json"))
    os.makedirs(f"{work}/social", exist_ok=True)
    snap, meta, feat, wk = b["snap"], b["meta"], b.get("featured"), b.get("week_event")
    load_season_logo(work, snap)
    W30, W15 = (b.get("win") or {}).get("d30"), (b.get("win") or {}).get("d15")
    season = {m["n"]: m for m in meta}
    champ = {m["n"]: (m["ch"][0][0] if m["ch"] else "") for m in meta}
    D0 = datetime.date.fromisoformat(snap["date"])
    dd = D0.strftime("%d/%m/%Y")
    de = D0.strftime("%b %d, %Y").replace(" 0", " ")
    issue = max(1, (D0 - datetime.date(2026, 11, 16)).days // 7 + 1)
    TOT = 5 if feat else 3
    files = []
    # classifica: ultimi 30 giorni se disponibili, altrimenti stagione
    if W30 and W30["meta"]:
        rank = sorted([[n, v[1], v[2], v[0]] for n, v in W30["meta"].items()], key=lambda x: -x[1])
        per = "last 30 days"
    else:
        rank = [[m["n"], m["share"], m["adj"], m["decks"]] for m in sorted(meta, key=lambda m: -m["share"])]
        per = "season"
    # 1 copertina
    im, d, y = _base(1, TOT, f"Week of {de}", f"Meta Report #{issue}")
    d.text((64, y), f"Season: {snap['season']}", font=_font("semi", 34), fill=GOLD)
    y += 80
    stats = [("events", W30["events"]), ("players", W30["players"]), ("matches", W30["matches"])] if W30 else [("events", snap["events"]), ("decklists", snap["decks"]), ("matches", snap["matches"])]
    for i, (lab, val) in enumerate(stats):
        x = 64 + i * 330
        d.rounded_rectangle([x, y, x + 300, y + 150], 22, fill=SURF, outline=LINE, width=2)
        d.text((x + 28, y + 26), f"{val:,}".replace(",", "."), font=_font("black", 54), fill=FG)
        d.text((x + 28, y + 100), lab.upper(), font=_font("semi", 22), fill=MUTED)
    y += 170
    d.text((64, y), f"Data from the {per}" if W30 else "Season data", font=_font("reg", 22), fill=MUTED)
    y += 56
    d.text((64, y), "MOST PLAYED", font=_font("semi", 24), fill=ACC)
    y += 50
    for i, r in enumerate(rank[:3]):
        d.rounded_rectangle([64, y, SW - 64, y + 120], 22, fill=SURF, outline=LINE, width=2)
        d.text((100, y + 60), f"{i+1}", font=_font("black", 56), fill=GOLD, anchor="lm")
        _dot(d, 186, y + 44, r[0])
        d.text((210, y + 26), r[0], font=_font("bold", 32), fill=FG)
        d.text((186, y + 72), f"{champ.get(r[0], '')} · win rate {r[2]}%", font=_font("reg", 24), fill=MUTED)
        d.text((SW - 100, y + 60), f"{r[1]}%", font=_font("black", 44), fill=FG, anchor="rm")
        y += 140
    if feat and y + 120 < SH - 110:
        d.rounded_rectangle([64, y + 6, SW - 64, y + 116], 22, outline=ACC, width=3)
        d.text((96, y + 30), "DECK OF THE WEEK", font=_font("semi", 20), fill=ACC)
        d.text((96, y + 60), f"{feat['arch']} · {feat['player']}", font=_font("bold", 28), fill=FG)
        d.text((SW - 96, y + 61), "swipe →", font=_font("semi", 24), fill=MUTED, anchor="ra")
    _footer(d)
    files.append("slide-1.jpg"); im.save(f"{work}/social/slide-1.jpg", quality=92)
    # 2 top 10
    im, d, y = _base(2, TOT, f"Meta share & win rate · {per}", "Top 10 archetypes")
    mx = max(r[1] for r in rank[:10])
    d.text((SW - 64, y - 6), "SHARE      WR", font=_font("semi", 20), fill=MUTED, anchor="ra")
    y += 30
    for i, r in enumerate(rank[:10]):
        d.text((64, y + 30), f"{i+1}", font=_font("bold", 30), fill=MUTED, anchor="lm")
        _dot(d, 120, y + 22, r[0], 8)
        f = _font("bold", 28)
        nm = r[0] if d.textlength(r[0], font=f) < 600 else r[0][:34] + "…"
        d.text((140, y + 6), nm, font=f, fill=FG)
        d.rounded_rectangle([140, y + 50, 140 + 540, y + 60], 5, fill=SURF)
        d.rounded_rectangle([140, y + 50, 140 + int(540 * r[1] / mx), y + 60], 5, fill=ACC)
        if per != "season" and r[0] in season:
            ch = round(r[1] - season[r[0]]["share"], 1)
            if abs(ch) >= 0.2:
                d.text((700, y + 55), ("▲ +" if ch > 0 else "▼ ") + f"{ch}", font=_font("semi", 20), fill=GOOD if ch > 0 else BAD, anchor="lm")
        d.text((SW - 190, y + 30), f"{r[1]}%", font=_font("bold", 30), fill=FG, anchor="rm")
        col = GOOD if (r[2] or 0) >= 52 else BAD if (r[2] or 0) < 48 else FG
        d.text((SW - 64, y + 30), f"{r[2]}%" if r[2] is not None else "—", font=_font("bold", 30), fill=col, anchor="rm")
        y += 88
    d.text((64, y + 6), "Win rate excludes mirrors · ▲▼ = share vs season average" if per != "season" else "Elo-adjusted win rate, mirrors excluded", font=_font("reg", 20), fill=MUTED)
    _footer(d)
    files.append("slide-2.jpg"); im.save(f"{work}/social/slide-2.jpg", quality=92)
    # 3 tendenze 15 giorni + evento della settimana
    im, d, y = _base(3, TOT, "Trends & results", "Rising & falling")
    if W15 and W15["meta"]:
        mv = [[n, round(v[1] - season[n]["share"], 1), v[1], v[2]] for n, v in W15["meta"].items() if n in season and (v[1] >= 1 or season[n]["share"] >= 1)]
        up = sorted([m for m in mv if m[1] > 0], key=lambda m: -m[1])[:4]
        dn = sorted([m for m in mv if m[1] < 0], key=lambda m: m[1])[:4]
        labs, note = ("RISING", "FALLING"), "Meta share over the last 15 days vs season average"
    else:
        tr = snap.get("trend", [])
        up = [[m[0], m[1], m[3], None] for m in tr if m[1] > 0][:4]
        dn = [[m[0], m[1], m[3], None] for m in tr if m[1] < 0][:4]
        labs, note = ("RISING", "FALLING"), "Meta share trend this season"
    for col, (lab, arr, c) in enumerate([(labs[0], up, GOOD), (labs[1], dn, BAD)]):
        x = 64 + col * 486
        d.text((x, y), lab, font=_font("semi", 24), fill=c)
        yy = y + 46
        for m in arr:
            d.rounded_rectangle([x, yy, x + 466, yy + 96], 18, fill=SURF, outline=LINE, width=2)
            _dot(d, x + 26, yy + 32, m[0], 7)
            f = _font("bold", 22)
            nm = m[0] if d.textlength(m[0], font=f) < 400 else m[0][:28] + "…"
            d.text((x + 44, yy + 18), nm, font=f, fill=FG)
            d.text((x + 26, yy + 56), f"{'+' if m[1] > 0 else ''}{m[1]} pts · now {m[2]}%", font=_font("reg", 21), fill=c)
            yy += 110
    y += 46 + 4 * 110
    d.text((64, y), note, font=_font("reg", 19), fill=MUTED)
    y += 48
    if wk and wk.get("top"):
        d.line([(64, y), (SW - 64, y)], fill=LINE, width=2)
        y += 24
        d.text((64, y), "BIGGEST EVENT OF THE WEEK", font=_font("semi", 22), fill=ACC)
        y += 36
        f = _font("bold", 30)
        nm = wk["name"] if d.textlength(wk["name"], font=f) < SW - 128 else wk["name"][:44] + "…"
        d.text((64, y), nm, font=f, fill=FG)
        d.text((64, y + 42), f"{datetime.date.fromisoformat(wk['date']).strftime('%b %d').replace(' 0', ' ')} · {wk['players']} players", font=_font("reg", 22), fill=MUTED)
        y += 88
        for i, tp in enumerate(wk["top"][:8]):
            x, yy = 64 + (i % 2) * 486, y + (i // 2) * 50
            if yy > SH - 140:
                break
            d.text((x, yy), _ord(tp[0]), font=_font("bold", 24), fill=GOLD)
            _dot(d, x + 62, yy + 14, tp[1], 6)
            f = _font("semi", 21)
            nm = tp[1] if d.textlength(tp[1], font=f) < 380 else tp[1][:30] + "…"
            d.text((x + 76, yy + 2), nm, font=f, fill=FG)
    _footer(d)
    files.append("slide-3.jpg"); im.save(f"{work}/social/slide-3.jpg", quality=92)
    if feat:
        L = _parse(feat["list"])
        pos = {1: "1st", 2: "2nd", 3: "3rd", 4: "Top 4"}.get(feat.get("rank", 1), "Top 8")
        sub = f"{feat['player']} · {pos} of {feat['size']} · {feat['event']}"
        pos_it = {1: "1°", 2: "2°", 3: "3°", 4: "Top 4"}.get(feat.get("rank", 1), "Top 8")
        # 4 material deck, grande
        im, d, y = _base(4, TOT, "Deck of the week", feat["arch"])
        f = _font("reg", 26)
        for line in _wrap(d, sub, f, SW - 128)[:2]:
            d.text((64, y - 6), line, font=f, fill=MUTED); y += 36
        y += 18
        d.text((64, y), f"MATERIAL DECK · {sum(q for q, _ in L['material'])}", font=_font("semi", 24), fill=ACC)
        y += 44
        _grid_best(im, d, work, imgmap, L["material"], 64, y, SW - 128, SH - 120 - y, qty=False, gap=16)
        _footer(d, "Card images © Weebs of the Shore")
        files.append("slide-4.jpg"); im.save(f"{work}/social/slide-4.jpg", quality=92)
        # 5 main deck + sideboard
        nmain, nside = sum(q for q, _ in L["main"]), sum(q for q, _ in L["side"])
        im, d, y = _base(5, TOT, f"{feat['arch']}", None)
        y -= 6
        avail = SH - 120 - y - 44 - (44 + 26 if L["side"] else 0)
        main_c, side_c = sorted(L["main"], key=lambda x: -x[0]), L["side"]
        best = None
        for cm in range(5, 11):  # carte piu' grandi possibili, evitando un'ultima riga quasi vuota
            for cs in range(max(4, min(len(side_c), 6)) if side_c else 6, 12):
                h = _grid_h(len(main_c), cm, SW - 128) + (_grid_h(len(side_c), cs, SW - 128) if side_c else 0)
                if h <= avail:
                    cw = (SW - 128 - 12 * (cm - 1)) / cm
                    last = len(main_c) % cm
                    score = cw - (40 if last and last <= cm // 3 else 0)
                    if best is None or score > best[0]:
                        best = (score, cm, cs)
                    break
        cm, cs = (best[1], best[2]) if best else (9, 11)
        d.text((64, y), f"MAIN DECK · {nmain}", font=_font("semi", 24), fill=ACC)
        y = _grid(im, d, work, imgmap, main_c, 64, y + 40, SW - 128, cm, gap=12) + 26
        if side_c:
            d.text((64, y), f"SIDEBOARD · {nside}", font=_font("semi", 24), fill=ACC)
            _grid(im, d, work, imgmap, side_c, 64, y + 40, SW - 128, cs, gap=12)
        _footer(d, "Card images © Weebs of the Shore")
        files.append("slide-5.jpg"); im.save(f"{work}/social/slide-5.jpg", quality=92)
    stories = make_stories(work, imgmap, snap, season, champ, rank, per, W30, W15, feat, de, issue)
    # didascalia di base (la sessione settimanale la riscrive)
    cap = [f"📊 META REPORT Grand Archive · settimana del {dd}", "",
           (f"Ultimi 30 giorni: {W30['events']} eventi e {W30['players']} giocatori analizzati." if W30 else f"Stagione {snap['season']}: {snap['events']} eventi."), "",
           "Top 5 del meta:"] + [f"{i+1}. {r[0]} — {r[1]}% (WR {r[2]}%)" for i, r in enumerate(rank[:5])]
    if wk:
        cap += ["", f"🏆 Evento più grande della settimana: {wk['name']} ({wk['players']} giocatori), vinto da {wk['top'][0][1] if wk['top'] else '—'}."]
    if feat:
        cap += ["", f"🃏 Lista della settimana: {feat['arch']} di {feat['player']} ({pos_it} su {feat['size']}, {feat['event']})."]
    cap += ["", f"Seguici su {HANDLE} per il meta report ogni lunedì!", "Dati: grandarchivestats.com. Immagini delle carte © Weebs of the Shore.", "",
            "#GrandArchive #GrandArchiveTCG #GATCG #TCG #TCGItalia #MetaReport #Decklist"]
    open(f"{work}/social/caption.txt", "w").write("\n".join(cap))
    json.dump(dict(date=snap["date"], ver=int(time.time()), slides=files, stories=stories, featured={k: feat[k] for k in ("arch", "player", "event", "date", "size", "rank")} if feat else None),
              open(f"{work}/social/social.json", "w"), ensure_ascii=False)
    log(f"OK post: {files} storie: {stories}")


# ---------------------------------------------------------------- comandi
def cmd_fetch(a):
    work = a.work
    os.makedirs(work, exist_ok=True)
    glossary = json.load(open(a.glossary))
    prev = json.loads(open(a.prev_bundle).read().replace("<\\/", "</")) if a.prev_bundle and os.path.exists(a.prev_bundle) else None
    prev_idx = json.load(open(a.prev_imgidx)) if a.prev_imgidx and os.path.exists(a.prev_imgidx) else {}
    snap, meta_rows = fetch_meta()
    champs = fetch_champions()
    cache = {}
    if a.prev_events and os.path.exists(a.prev_events):
        cache = {e["id"]: e for e in json.load(open(a.prev_events))}
    events = fetch_events(31, cache, snap["date"])
    json.dump(list(events.values()), open(f"{work}/events.json", "w"), ensure_ascii=False, separators=(",", ":"))
    season_names = [m["n"] for m in meta_rows if m["decks"] >= MIN_DECKS]
    w30 = window_stats(events, 30, snap["date"], set(m["n"] for m in meta_rows))
    names = season_names + [n for n, v in sorted(w30["meta"].items(), key=lambda x: -x[1][0]) if v[0] >= 8 and n not in season_names and any(m["n"] == n for m in meta_rows)]
    arch = fetch_archetypes(names)
    major = fetch_major()
    cards = fetch_cards(work)
    idx, new_sheets = build_images(work, cards, prev_idx)
    json.dump(idx, open(f"{work}/imgidx.json", "w"))
    pil = {}
    for c in champs:
        for r in c["rows"]:
            if r[1]:
                pil.setdefault(r[1], []).append([c["name"], r[2]])
    mrow = {m["n"]: m for m in meta_rows}
    meta = [dict(n=n, tier=mrow[n]["tier"], decks=mrow[n]["decks"], share=mrow[n]["share"], wr=mrow[n]["wr"], adj=mrow[n]["adj"],
                 ch=sorted(pil.get(n, []), key=lambda x: -x[1])) for n in names]
    S = set(names)
    h2h = {n: {o: v for o, v in arch[n]["h2h"].items() if o in S} for n in names}
    cons = {n: dict(material=arch[n]["material"], main=arch[n]["main"], side=arch[n]["side"], best=arch[n]["best"] or {}) for n in names}
    n_sheets = (max(v[0] for v in idx.values()) + 1) if idx else 0
    counts = [0] * n_sheets
    for v in idx.values():
        counts[v[0]] = max(counts[v[0]], v[1] + 1)
    U = set(names)
    wins = {}
    for d in (30, 15):
        w = window_stats(events, d, snap["date"], U)
        w["meta"] = {k: v for k, v in w["meta"].items() if k in U}
        wins[f"d{d}"] = w
    history = (prev or {}).get("featured_history", [])
    feat = pick_featured_events(events, snap["date"], history)
    if feat:
        history = [h for h in history if h.get("date") != snap["date"]] + [dict(date=snap["date"], arch=feat["arch"], player=feat["player"], event=feat["event"])]
    bundle = dict(snap=snap, meta=meta, win=wins, week_event=week_event(events, snap["date"]), featured_history=history[-20:], h2h=h2h, cons=cons, champs=champs, top=[m["n"] for m in sorted(meta, key=lambda x: -x["share"])[:20]],
                  major=major, osaka=(major or {}).get("top", []), glossary=[[k, v["kind"], v["def_"]] for k, v in glossary.items()],
                  sheets=counts, cards=card_rows(cards, idx, n_sheets, glossary, cons), weekly=None)
    # variazioni rispetto alla settimana precedente
    weekly = dict(date=snap["date"], season=snap["season"], new_cards=[], movers=[], new_archetypes=[], dropped=[], top10=[])
    if prev:
        pm = {m["n"]: m for m in prev.get("meta", [])}
        for m in meta:
            p = pm.get(m["n"])
            if p:
                weekly["movers"].append([m["n"], round(m["share"] - p["share"], 1), round(m["adj"] - p["adj"], 1), m["share"], m["adj"]])
            else:
                weekly["new_archetypes"].append([m["n"], m["share"], m["adj"]])
        weekly["dropped"] = [n for n in pm if n not in S]
        weekly["movers"] = [m for m in weekly["movers"] if m[1] or m[2]]
        weekly["movers"].sort(key=lambda x: -abs(x[1]))
        weekly["movers"] = weekly["movers"][:12]
        old_cards = {r[0] for r in prev.get("cards", [])}
        weekly["new_cards"] = [r[0] for r in bundle["cards"] if r[0] not in old_cards][:80]
        weekly["prev_date"] = prev.get("snap", {}).get("date")
        weekly["prev_season"] = prev.get("snap", {}).get("season")
    weekly["top10"] = [[m["n"], m["tier"], m["share"], m["adj"], m["decks"]] for m in sorted(meta, key=lambda x: -x["share"])[:10]]
    weekly["major"] = {k: major[k] for k in ("name", "date", "players")} | {"top8": [[t["rank"], t["deck"], t["player"]] for t in major["top"]]} if major else None
    bundle["delta"] = weekly
    bundle["featured"] = feat or pick_featured(cons, meta, major, snap["date"])
    s = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    open(f"{work}/bundle.json", "w").write(s)
    json.dump(weekly, open(f"{work}/weekly_input.json", "w"), ensure_ascii=False, indent=1)
    log(f"OK bundle {len(s)//1024} KB · archetipi {len(meta)} · carte {len(bundle['cards'])} · fogli nuovi {new_sheets}")
    print(json.dumps(dict(new_sheets=new_sheets, archetypes=len(meta), cards=len(bundle["cards"]), season=snap["season"])))


def cmd_build(a):
    b = json.loads(open(f"{a.work}/bundle.json").read())
    if a.weekly and os.path.exists(a.weekly):
        b["weekly"] = dict(date=b["snap"]["date"], md=open(a.weekly).read().strip())
    sj = f"{a.work}/social/social.json"
    if os.path.exists(sj):
        s = json.load(open(sj))
        cap = f"{a.work}/social/caption.txt"
        s["caption"] = open(cap).read().strip() if os.path.exists(cap) else ""
        b["social"] = s
    tpl = open(a.template).read()
    assert tpl.count("/*__DATA__*/null") == 1, "segnaposto dati mancante nel template"
    s = json.dumps(b, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    open(a.out, "w").write(tpl.replace("/*__DATA__*/null", s))
    log(f"OK pagina {os.path.getsize(a.out)//1024} KB -> {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("fetch")
    f.add_argument("--work", required=True)
    f.add_argument("--prev-bundle")
    f.add_argument("--prev-imgidx")
    f.add_argument("--prev-events")
    f.add_argument("--glossary", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json"))
    so = sp.add_parser("social")
    so.add_argument("--work", required=True)
    b = sp.add_parser("build")
    b.add_argument("--work", required=True)
    b.add_argument("--template", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--weekly")
    t = sp.add_parser("thumbs")
    t.add_argument("--work", required=True)
    a = ap.parse_args()
    {"fetch": cmd_fetch, "build": cmd_build, "social": cmd_social, "thumbs": cmd_thumbs}[a.cmd](a)
