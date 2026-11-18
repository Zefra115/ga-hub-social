#!/usr/bin/env python3
"""News di Grand Archive inoltrate su Discord -> storie (e, su richiesta, post) Instagram per GA.Hub.

Flusso: l'utente inoltra nel canale #news del server "Grand Archive TCG ITALIA" i messaggi del
Discord ufficiale. Il bot "GA.Hub News" legge il canale (token = segreto di rete dell'ambiente per
discord.com, iniettato dal proxy: qui si manda un valore fittizio). Si considerano SOLO i messaggi
degli autori autorizzati (AUTHORS).

Un messaggio di testo di un autore autorizzato che contiene la parola "post" (es. "post", "fai un post")
segna la news inoltrata subito prima come "da pubblicare anche come post nel feed".

Comandi:
  scan  --work DIR [--state news/state.json]
        legge i messaggi nuovi (dopo state.last_id), scarica le immagini e genera in DIR:
        manifest.json, <id>-<n>-story.jpg (1080x1920) e, per le news con "post", <id>-<n>-post.jpg (1080x1350).
        Non pubblica nulla e non modifica lo stato.
  render --work DIR   rigenera le immagini da DIR/manifest.json (dopo aver corretto a mano il "kicker").
  done  --last-id ID [--state news/state.json]
        segna come gestiti tutti i messaggi fino a ID (da usare dopo la pubblicazione o se l'utente
        dice di saltarli).
"""
import argparse, datetime, importlib.util, json, os, re, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://discord.com/api/v10"
CHANNEL = "1571935765556891738"          # #news nel server Grand Archive TCG ITALIA
AUTHORS = {"402588692864040960"}        # zefra115
HDR = {"Authorization": "Bot PROXY_INJECTS_TOKEN", "User-Agent": "DiscordBot (https://github.com/Zefra115/ga-hub-social, 1.0)"}
ST_W, ST_H = 1080, 1920
SOURCES = {"1111896508816695406": "official Grand Archive Discord"}


def _pipeline():
    spec = importlib.util.spec_from_file_location("gapipe", os.path.join(HERE, "pipeline.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def api(path):
    for i in range(4):
        req = urllib.request.Request(API + path, headers=HDR)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)) + 0.5)
                continue
            raise SystemExit(f"ERRORE Discord {e.code} su {path}: {e.read().decode(errors='replace')[:300]}")
    raise SystemExit("ERRORE Discord: troppi rate limit")


def download(url, dest):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HDR["User-Agent"]})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
            return
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 + i * 3)
    raise SystemExit(f"ERRORE download {url}: {err}")


def clean_text(s):
    s = re.sub(r"<a?:(\w+):\d+>", "", s or "")          # emoji personalizzate
    s = re.sub(r"<@[&!]?\d+>|@everyone|@here", "", s)     # menzioni
    s = re.sub(r"<#\d+>", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def load_state(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except FileNotFoundError:
        return {"last_id": "0"}


def cmd_scan(a):
    st = load_state(a.state)
    os.makedirs(a.work, exist_ok=True)
    msgs, after = [], st.get("last_id", "0")
    while True:
        page = api(f"/channels/{CHANNEL}/messages?limit=100&after={after}")
        if not page:
            break
        page.sort(key=lambda m: int(m["id"]))
        msgs += page
        after = page[-1]["id"]
        if len(page) < 100:
            break
    items, last_seen = [], st.get("last_id", "0")
    for m in msgs:
        last_seen = m["id"]
        if m["author"]["id"] not in AUTHORS:
            continue
        snaps = m.get("message_snapshots") or []
        src_msg = snaps[0]["message"] if snaps else m
        atts = [x for x in src_msg.get("attachments", []) if (x.get("content_type") or "").startswith("image/")]
        for e in src_msg.get("embeds", []):  # immagini dentro gli embed (link a X, ecc.)
            for k in ("image", "thumbnail"):
                if e.get(k, {}).get("url"):
                    atts.append({"url": e[k]["url"], "filename": "embed.jpg"})
                    break
        text = clean_text(src_msg.get("content", ""))
        if not snaps and not atts:
            if re.search(r"\bpost\b", m.get("content", ""), re.I) and items:
                items[-1]["post"] = True          # nota "post" dopo un inoltro
                items[-1]["note"] = m["content"].strip()
            continue
        ref = m.get("message_reference") or {}
        it = {"id": m["id"], "forwarded_at": m["timestamp"], "original_at": src_msg.get("timestamp"),
              "source": SOURCES.get(ref.get("guild_id"), "Discord"), "text": text, "post": False,
              "kicker": "News", "images": []}
        for n, x in enumerate(atts, 1):
            f = os.path.join(a.work, f"{m['id']}-{n}-src" + os.path.splitext(x.get("filename") or ".jpg")[1].split("?")[0].lower()[:5])
            download(x["url"], f)
            it["images"].append(f)
        items.append(it)
    man = {"scanned_at": datetime.datetime.now().isoformat(timespec="seconds"), "prev_last_id": st.get("last_id", "0"),
           "last_id": last_seen, "items": items}
    json.dump(man, open(os.path.join(a.work, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    render(a.work, man)
    print(json.dumps({"news": len(items), "posts": sum(i["post"] for i in items), "last_id": last_seen,
                      "files": sorted(x for x in os.listdir(a.work) if x.endswith(("-story.jpg", "-post.jpg")))}, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ grafica
GA_LOGO = os.path.join(HERE, "..", "assets", "ga-logo.png")   # logo Grand Archive (estratto da un banner ufficiale)
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"


def find_card(src):
    """Trova la carta in un'immagine spoiler: il riquadro scuro (bordo della carta) più grande
    con proporzioni da carta (~0.72). Ritorna (x0, y0, x1, y1) in pixel oppure None."""
    import numpy as np
    a = np.asarray(src.convert("RGB")).max(axis=2) < 50
    H, W = a.shape

    def longest(col):
        best = cur = s = bs = 0
        for i, v in enumerate(col):
            if v:
                if cur == 0:
                    s = i
                cur += 1
                if cur > best:
                    best, bs = cur, s
            else:
                cur = 0
        return best, bs

    good = []
    for x in range(W):
        n, s = longest(a[:, x])
        if n > 0.35 * H:
            good.append((x, n, s))
    if len(good) < 2:
        return None
    groups, cur = [], [good[0]]
    for g in good[1:]:
        if g[0] - cur[-1][0] > 3:
            groups.append(cur)
            cur = [g]
        else:
            cur.append(g)
    groups.append(cur)
    best = None
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            L, R = groups[i], groups[j]
            x0, x1 = L[0][0], R[-1][0]
            cols = L + R
            y0 = int(np.median([c[2] for c in cols]))
            y1 = int(np.median([c[2] + c[1] for c in cols]))
            w, h = x1 - x0, y1 - y0
            if h > 0 and 0.64 < w / h < 0.80 and (best is None or w * h > best[0]):
                best = (w * h, (x0, y0, x1, y1))
    return best[1] if best else None


def find_cards(src):
    """Tutte le carte di un'immagine con più carte affiancate (es. ban list): coppie di bordi scuri
    consecutivi con proporzioni da carta. Ritorna una lista di box (x0, y0, x1, y1) da sinistra a destra."""
    import numpy as np
    a = np.asarray(src.convert("RGB")).max(axis=2) < 50
    H, W = a.shape
    good = []
    for x in range(W):
        col = a[:, x]
        best = cur = s = bs = 0
        for i, v in enumerate(col):
            if v:
                if cur == 0:
                    s = i
                cur += 1
                if cur > best:
                    best, bs = cur, s
            else:
                cur = 0
        if best > 0.3 * H:
            good.append((x, best, bs))
    if len(good) < 2:
        return []
    groups, cur = [], [good[0]]
    for g in good[1:]:
        if g[0] - cur[-1][0] > 3:
            groups.append(cur)
            cur = [g]
        else:
            cur.append(g)
    groups.append(cur)
    out, i = [], 0
    while i < len(groups) - 1:
        L, R = groups[i], groups[i + 1]
        x0, x1 = L[0][0], R[-1][0]
        cols = L + R
        y0 = int(np.median([c[2] for c in cols]))
        y1 = int(np.median([c[2] + c[1] for c in cols]))
        w, h = x1 - x0, y1 - y0
        if h > 0 and 0.64 < w / h < 0.80:
            out.append((x0, y0, x1, y1))
            i += 2
        else:
            i += 1
    return out


TITLES = {"spoiler": ("SPOILER ALERT", "🔥"), "ban list": ("BAN LIST", "🚫")}


def _emoji(ch, size):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(EMOJI_FONT, 109)
    im = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 0), ch, font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    return im.resize((int(im.width * size / im.height), size), Image.LANCZOS)


def _cover(src, W, H, blur, bright):
    from PIL import Image, ImageFilter, ImageEnhance
    s = max(W / src.width, H / src.height)
    bg = src.resize((int(src.width * s) + 1, int(src.height * s) + 1), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    return ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(blur))).enhance(bright)


def _cover_bg(P, src, W, H):
    from PIL import Image
    return Image.blend(_cover(src, W, H, 40, 0.35), Image.new("RGB", (W, H), P.BG), 0.35)


def _shade(im, top_h, bot_h, color):
    """Sfumature scure in alto e in basso per leggere testi e loghi sopra lo sfondo."""
    from PIL import Image
    W, H = im.size
    g = Image.new("L", (1, H), 0)
    for y in range(H):
        a = 0
        if y < top_h:
            a = 1 - y / top_h
        elif y > H - bot_h:
            a = (y - (H - bot_h)) / bot_h
        g.putpixel((0, y), int(235 * min(1, a * 1.15)))
    im.paste(Image.new("RGB", im.size, color), (0, 0), g.resize(im.size))


def _header(P, im, W, top):
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([64, top + 62, 114, top + 112], 13, fill=P.ACC)
    d.text((89, top + 87), "GA", font=P._font("black", 21), fill=P.BG, anchor="mm")
    d.text((130, top + 64), P.BRAND, font=P._font("black", 24), fill=P.FG)
    d.text((130, top + 92), f"{P.HANDLE} · Grand Archive TCG", font=P._font("reg", 18), fill=P.MUTED)
    right = W - 64
    if P.LOGO is not None:  # logo dell'espansione, sempre in alto a destra
        im.paste(P.LOGO, (right - P.LOGO.width, top + 42), P.LOGO)
        right -= P.LOGO.width + 22
    if os.path.exists(GA_LOGO):  # logo Grand Archive accanto
        ga = Image.open(GA_LOGO).convert("RGBA")
        h = 62
        ga = ga.resize((int(ga.width * h / ga.height), h), Image.LANCZOS)
        im.paste(ga, (right - ga.width, top + 42 + (88 - h) // 2), ga)
    return d


def _footer_block(P, d, W, fy, source):
    d.line([(64, fy), (W - 64, fy)], fill=P.LINE, width=2)
    d.text((64, fy + 22), f"Source: {source}", font=P._font("reg", 22), fill=P.MUTED)
    d.text((64, fy + 54), "Card images © Weebs of the Shore", font=P._font("reg", 22), fill=P.MUTED)
    d.text((W - 64, fy + 22), P.HANDLE, font=P._font("bold", 24), fill=P.ACC, anchor="ra")


def _frame(P, W, H, src, kicker, source, area_top, area_bot):
    from PIL import Image, ImageDraw
    im = _cover_bg(P, src, W, H)
    top = 170 if H > 1500 else 0
    d = _header(P, im, W, top)
    ky = top + 170
    f = P._font("black", 30)
    tw = d.textlength(kicker.upper(), font=f)
    d.rounded_rectangle([64, ky, 64 + tw + 40, ky + 54], 27, fill=P.ACC)
    d.text((84, ky + 27), kicker.upper(), font=f, fill=P.BG, anchor="lm")
    box_w, box_t, box_b = W - 80, ky + 54 + 40, H - area_bot
    s = min(box_w / src.width, (box_b - box_t) / src.height)
    img = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    x, y = (W - img.width) // 2, box_t + (box_b - box_t - img.height) // 2
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], 22, fill=255)
    d.rounded_rectangle([x - 3, y - 3, x + img.width + 2, y + img.height + 2], 25, outline=P.LINE, width=3)
    im.paste(img, (x, y), mask)
    _footer_block(P, d, W, H - area_bot + 40 if H > 1500 else H - 116, source)
    return im


_SR = {"ready": None}


def _super_res(card, work=None):
    """Super-resolution x2 con EDSR (OpenCV dnn_superres) per le carte piccole.
    Serve la cartella indicata da GAHUB_SR (vedi tools/setup_sr.sh) con pylib/ e EDSR_x2.pb.
    Se manca, ritorna la carta com'è (si usa il ridimensionamento normale)."""
    import hashlib, io
    from PIL import Image
    base = os.environ.get("GAHUB_SR")
    if not base or not os.path.exists(os.path.join(base, "EDSR_x2.pb")):
        return card
    if _SR["ready"] is None:
        try:
            sys.path.insert(0, os.path.join(base, "pylib"))
            import cv2  # noqa: F401
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(os.path.join(base, "EDSR_x2.pb"))
            sr.setModel("edsr", 2)
            _SR["ready"], _SR["sr"], _SR["cv2"] = True, sr, cv2
        except Exception as e:  # noqa: BLE001
            print("super-resolution non disponibile:", e, file=sys.stderr)
            _SR["ready"] = False
    if not _SR["ready"]:
        return card
    buf = io.BytesIO()
    card.save(buf, "PNG")
    key = hashlib.md5(buf.getvalue()).hexdigest()
    cache = os.path.join(work or base, f"sr-{key}.png")
    if os.path.exists(cache):
        return Image.open(cache).convert("RGB")
    import numpy as np
    cv2 = _SR["cv2"]
    up = _SR["sr"].upsample(cv2.cvtColor(np.asarray(card.convert("RGB")), cv2.COLOR_RGB2BGR))
    out = Image.fromarray(cv2.cvtColor(up, cv2.COLOR_BGR2RGB))
    out.save(cache)
    return out


def _tight(card, thr=70, frac=0.6):
    """Toglie bordi scuri e sfondo attorno alla carta: tiene righe/colonne in cui la maggior parte dei pixel non è scura."""
    import numpy as np
    m = np.asarray(card.convert("RGB")).max(axis=2) > thr
    cols = np.where(m.mean(axis=0) > frac)[0]
    rows = np.where(m.mean(axis=1) > frac)[0]
    if len(cols) < card.width * 0.5 or len(rows) < card.height * 0.5:
        return card
    return card.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))


def _cards(P, W, H, src, boxes, label, emo, subtitle, source, pad=0.0, work=None):
    """Carte grandi e leggibili (1 al centro; 2 affiancate; 3-4 su due righe), artwork della prima carta
    sfocato dietro, titolo con emoji (es. 🔥 SPOILER ALERT 🔥, 🚫 BAN LIST 🚫)."""
    from PIL import Image, ImageDraw, ImageFilter
    story = H > 1500
    from PIL import ImageOps
    cards = [src.crop(b) for b in boxes]
    if pad:  # carta ritagliata stretta sulla cornice colorata
        cards = [_tight(c) for c in cards]
    # carte piccole (es. catture da video): super-resolution x2 prima di ingrandirle
    cards = [_super_res(c, work) if c.width < 650 else c for c in cards]
    if pad:  # bordo nero uniforme su tutti i lati
        cards = [ImageOps.expand(c, border=max(2, int(c.width * pad)), fill=(14, 14, 16)) for c in cards]
    cw, ch = cards[0].size
    art = cards[0].crop((int(cw * .06), int(ch * .09), int(cw * .94), int(ch * .58)))  # illustrazione della carta
    im = _cover(art, W, H, 22, 0.62)
    _shade(im, 560 if story else 330, 520 if story else 260, P.BG)
    top = 170 if story else 0
    d = _header(P, im, W, top)
    ty = top + (190 if story else 160)
    tsize = 66 if story else 56
    f = P._font("black", tsize)
    tw = d.textlength(label, font=f)
    e = _emoji(emo, int(tsize * 1.05))
    total = tw + 2 * (e.width + 22)
    x = int((W - total) / 2)
    im.paste(e, (x, ty - 4), e)
    d.text((x + e.width + 22, ty + tsize // 2), label, font=f, fill=P.FG, anchor="lm")
    im.paste(e, (int(x + e.width + 44 + tw), ty - 4), e)
    y = ty + tsize + 22
    if subtitle:
        d.text((W // 2, y), subtitle, font=P._font("semi", 30 if story else 26), fill=P.GOLD, anchor="ma")
        y += 50
    foot = H - 400 + 40 if story else H - 116
    n = len(cards)
    cols = 1 if n == 1 else 2
    rows = (n + cols - 1) // cols
    gap = 36
    area_t, area_b = y + 20, foot - 40
    ratio = cw / ch
    th = int(min((area_b - area_t - gap * (rows - 1)) / rows,
                 ((W - 300) if n == 1 and story else (W - 128 - gap * (cols - 1)) / cols) / ratio))
    tw_ = int(th * ratio)
    oy = area_t + (area_b - area_t - (rows * th + gap * (rows - 1))) // 2
    for k, card in enumerate(cards):
        r, c = divmod(k, cols)
        in_row = min(cols, n - r * cols)
        rw = in_row * tw_ + (in_row - 1) * gap
        cx = (W - rw) // 2 + c * (tw_ + gap)
        cy = oy + r * (th + gap)
        big = card.resize((tw_, th), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.2, 45, 2))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle([cx - 8, cy - 8, cx + tw_ + 8, cy + th + 8], 34, fill=P.ACC + (110,))
        glow = glow.filter(ImageFilter.GaussianBlur(24))
        im.paste(glow, (0, 0), glow)
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([cx + 6, cy + 14, cx + tw_ + 6, cy + th + 14], 26, fill=(0, 0, 0, 170))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        im.paste(shadow, (0, 0), shadow)
        mask = Image.new("L", big.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw_ - 1, th - 1], int(tw_ * 0.045), fill=255)
        im.paste(big, (cx, cy), mask)
    d = ImageDraw.Draw(im)
    _footer_block(P, d, W, foot, source)
    return im


def _spoiler(P, W, H, src, box, subtitle, source):
    return _cards(P, W, H, src, [box], "SPOILER ALERT", "🔥", subtitle, source)


def render(work, man):
    from PIL import Image
    P = _pipeline()
    try:
        P.load_season_logo(work, {"season": man.get("season", ".asphodel/paradise")})
    except Exception as e:  # noqa: BLE001
        print("logo stagione non disponibile:", e, file=sys.stderr)
    for it in man["items"]:
        it["stories"], it["posts"] = [], []
        kicker = it.get("kicker") or "News"
        for n, f in enumerate(it["images"], 1):
            src = Image.open(f).convert("RGB")
            boxes = []
            k = kicker.lower()
            if k in TITLES:
                cb = (it.get("card_boxes") or {}).get(str(n))  # correzione manuale: frazioni [x0,y0,x1,y1] o lista di box
                if cb:
                    cb = cb if isinstance(cb[0], list) else [cb]
                    boxes = [tuple(int(v * (src.width if i % 2 == 0 else src.height)) for i, v in enumerate(bx)) for bx in cb]
                elif k == "spoiler":
                    bx = find_card(src)
                    boxes = [bx] if bx else []
                else:
                    boxes = find_cards(src)
                it.setdefault("found_cards", {})[str(n)] = [list(bx) for bx in boxes] or None
            for kind, (W, H) in (("story", (ST_W, ST_H)), ("post", (P.SW, P.SH))):
                if kind == "post" and not it.get("post"):
                    continue
                if boxes:
                    label, emo = TITLES[k]
                    out_im = _cards(P, W, H, src, boxes, label, emo, it.get("subtitle", ""), it["source"], it.get("card_pad", 0.0), work)
                else:
                    out_im = _frame(P, W, H, src, kicker, it["source"], 0, 400 if kind == "story" else 130)
                out = os.path.join(work, f"{it['id']}-{n}-{kind}.jpg")
                out_im.save(out, quality=95, subsampling=0)  # niente sottocampionamento colore: testo più nitido
                it["stories" if kind == "story" else "posts"].append(os.path.basename(out))
    json.dump(man, open(os.path.join(work, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "render", "done"])
    ap.add_argument("--work")
    ap.add_argument("--state", default=os.path.join(HERE, "..", "news", "state.json"))
    ap.add_argument("--last-id")
    a = ap.parse_args()
    if a.cmd == "scan":
        cmd_scan(a)
    elif a.cmd == "render":
        man = json.load(open(os.path.join(a.work, "manifest.json"), encoding="utf-8"))
        render(a.work, man)
        print("ok")
    else:
        st = load_state(a.state)
        if int(a.last_id) > int(st.get("last_id", "0")):
            st["last_id"] = a.last_id
        st["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(a.state), exist_ok=True)
        json.dump(st, open(a.state, "w", encoding="utf-8"), indent=1)
        print(json.dumps(st))


if __name__ == "__main__":
    main()
