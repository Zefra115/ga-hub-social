#!/usr/bin/env python3
"""Rulings 101: carosello settimanale di regole per neofiti (GA.Hub).

Ogni puntata è un file JSON in rulings/NNN-slug.json (testi delle slide in inglese, didascalia in
italiano a parte). Ogni regola citata va verificata su rules.gatcg.com (le pagine sono disponibili
in Markdown aggiungendo .md all'URL; indice in https://rules.gatcg.com/llms.txt) e la fonte va
indicata nel campo "sources" della puntata.

  python3 -I tools/rulings.py render --spec rulings/001-main-vs-material.json --out DIR

Tipi di slide:
  cover    kicker, title, subtitle, cards[{name, edition?, label}]
  rules    kicker, title, bullets[...], cards[...], note
  steps    kicker, title, steps[{title, text}], cards[...] (mostrate in fila con frecce)
  recap    kicker, title, bullets[...], note, cta
Le carte si cercano per nome su api.gatcg.com; "edition" (prefisso del set, es. "PRD") sceglie la stampa.
"""
import argparse, importlib.util, json, os, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.gatcg.com"


def _pipeline():
    spec = importlib.util.spec_from_file_location("gapipe", os.path.join(HERE, "pipeline.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def card_image(name, edition, cache):
    from PIL import Image
    os.makedirs(cache, exist_ok=True)
    key = "".join(ch for ch in f"{name}-{edition or ''}" if ch.isalnum() or ch in "-_")
    f = os.path.join(cache, key + ".jpg")
    if not os.path.exists(f):
        req = urllib.request.Request(f"{API}/cards/search?name={urllib.parse.quote(name)}", headers={"User-Agent": "gahub-rulings/1.0"})
        data = json.load(urllib.request.urlopen(req, timeout=40))["data"]
        card = next((c for c in data if c["name"].lower() == name.lower()), None)
        if not card:
            raise SystemExit(f"ERRORE: carta non trovata nell'indice: {name}")
        eds = card["editions"]
        ed = next((e for e in eds if edition and (e.get("set") or {}).get("prefix") == edition), None) or eds[-1]
        req = urllib.request.Request(API + ed["image"], headers={"User-Agent": "gahub-rulings/1.0"})
        open(f, "wb").write(urllib.request.urlopen(req, timeout=60).read())
    return Image.open(f).convert("RGB")


def _rounded(img, r):
    from PIL import Image, ImageDraw
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], r, fill=255)
    return m


def _paste_card(P, im, card, x, y, h, label=None):
    from PIL import Image, ImageDraw, ImageFilter
    w = int(card.width * h / card.height)
    c = card.resize((w, h), Image.LANCZOS)
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x + 4, y + 12, x + w + 4, y + h + 12], 22, fill=(0, 0, 0, 150))
    im.paste(sh.filter(ImageFilter.GaussianBlur(12)), (0, 0), sh.filter(ImageFilter.GaussianBlur(12)))
    im.paste(c, (x, y), _rounded(c, int(w * 0.045)))
    if label:
        d = ImageDraw.Draw(im)
        f = P._font("semi", 22)
        d.text((x + w // 2, y + h + 18), label.upper(), font=f, fill=P.MUTED, anchor="ma")
    return w


def _card_row(P, im, cards, y, h, cache, gap=36, arrows=False):
    from PIL import ImageDraw
    imgs = [card_image(c["name"], c.get("edition"), cache) for c in cards]
    ws = [int(i.width * h / i.height) for i in imgs]
    aw = 70 if arrows else 0
    total = sum(ws) + (gap + aw) * (len(ws) - 1)
    if total > P.SW - 128:  # riduci se non ci stanno
        k = (P.SW - 128 - (gap + aw) * (len(ws) - 1)) / sum(ws)
        h = int(h * k)
        ws = [int(w * k) for w in ws]
        total = sum(ws) + (gap + aw) * (len(ws) - 1)
    x = (P.SW - total) // 2
    d = ImageDraw.Draw(im)
    for i, (img, c) in enumerate(zip(imgs, cards)):
        _paste_card(P, im, img, x, y, h, c.get("label"))
        x += ws[i]
        if arrows and i < len(imgs) - 1:
            cx, cy = x + (gap + aw) // 2, y + h // 2
            d.polygon([(cx - 18, cy - 22), (cx + 20, cy), (cx - 18, cy + 22)], fill=P.ACC)
        x += gap + aw
    return y + h + (56 if any(c.get("label") for c in cards) else 0)


def _bullets(P, d, items, y, size=34, numbered=False, maxw=None):
    f = P._font("semi", size)
    maxw = maxw or P.SW - 128 - 64
    for i, it in enumerate(items, 1):
        lines = P._wrap(d, it, f, maxw)
        cy = y + int(size * 0.62)
        if numbered:
            d.ellipse([64, cy - 22, 108, cy + 22], fill=P.ACC)
            d.text((86, cy), str(i), font=P._font("black", 24), fill=P.BG, anchor="mm")
        else:
            d.rounded_rectangle([70, cy - 9, 88, cy + 9], 5, fill=P.ACC)
        for ln in lines:
            d.text((128, y), ln, font=f, fill=P.FG)
            y += int(size * 1.3)
        y += int(size * 0.55)
    return y


def render(spec, out, cache):
    P = _pipeline()
    os.makedirs(cache, exist_ok=True)
    try:
        P.load_season_logo(cache, {"season": spec.get("season", ".asphodel/paradise")})
    except Exception as e:  # noqa: BLE001
        print("logo stagione non disponibile:", e, file=sys.stderr)
    os.makedirs(out, exist_ok=True)
    slides = spec["slides"]
    tot = len(slides)
    foot = "Rules: rules.gatcg.com · Card images © Weebs of the Shore"
    files = []
    for n, s in enumerate(slides, 1):
        kind = s["type"]
        if kind == "cover":
            im, d, y = P._base(n, tot, s.get("kicker", ""), s["title"], tsize=88)
            if s.get("subtitle"):
                for ln in P._wrap(d, s["subtitle"], P._font("reg", 34), P.SW - 128):
                    d.text((64, y), ln, font=P._font("reg", 34), fill=P.MUTED)
                    y += 46
            if s.get("cards"):
                _card_row(P, im, s["cards"], y + 50, P.SH - 130 - (y + 50) - 70, cache, gap=60)
        else:
            im, d, y = P._base(n, tot, s.get("kicker", ""), s["title"], tsize=s.get("tsize", 58))
            y += 14
            if kind == "recap":
                y = _bullets(P, d, s["bullets"], y + 20, size=s.get("size", 40))
            elif kind == "rules":
                y = _bullets(P, d, s["bullets"], y, size=s.get("size", 34))
            elif kind == "steps":
                for i, st in enumerate(s["steps"], 1):
                    cy = y + 22
                    d.ellipse([64, cy - 22, 108, cy + 22], fill=P.ACC)
                    d.text((86, cy), str(i), font=P._font("black", 24), fill=P.BG, anchor="mm")
                    d.text((128, y), st["title"], font=P._font("bold", 32), fill=P.FG)
                    y += 46
                    for ln in P._wrap(d, st["text"], P._font("reg", 28), P.SW - 128 - 64):
                        d.text((128, y), ln, font=P._font("reg", 28), fill=P.MUTED)
                        y += 38
                    y += 22
            if s.get("cards"):
                room = P.SH - 130 - y - 30 - (56 if any(c.get("label") for c in s["cards"]) else 0)
                if s.get("note"):
                    room -= 70
                y = _card_row(P, im, s["cards"], y + 20, min(s.get("card_h", 470), room), cache, arrows=(kind == "steps"))
            if s.get("note"):
                f = P._font("reg", 24)
                lines = P._wrap(d, s["note"], f, P.SW - 128 - 40)
                bh = 30 + 34 * len(lines)
                by = y + 20 if kind == "recap" else P.SH - 130 - bh - 10
                y = by + bh
                d.rounded_rectangle([64, by, P.SW - 64, by + bh], 16, fill=P.SURF, outline=P.LINE, width=2)
                for i, ln in enumerate(lines):
                    d.text((84, by + 15 + 34 * i), ln, font=f, fill=P.MUTED)
            if kind == "recap" and s.get("cta"):
                f = P._font("bold", 32)
                d.rounded_rectangle([64, y + 50, P.SW - 64, y + 150], 50, outline=P.GOLD, width=3)
                d.text((P.SW // 2, y + 100), s["cta"], font=f, fill=P.GOLD, anchor="mm")
        P._footer(d, foot)
        fn = os.path.join(out, f"slide-{n}.jpg")
        im.save(fn, quality=92)
        files.append(fn)
    if spec.get("caption"):
        open(os.path.join(out, "caption.txt"), "w", encoding="utf-8").write(spec["caption"].strip() + "\n")
    print(json.dumps({"slides": files}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["render"])
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    render(spec, a.out, a.cache or os.path.join(a.out, "_cache"))


if __name__ == "__main__":
    main()
