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
def _cover_bg(P, src, W, H):
    from PIL import Image, ImageFilter, ImageEnhance
    s = max(W / src.width, H / src.height)
    bg = src.resize((int(src.width * s) + 1, int(src.height * s) + 1), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)
    return Image.blend(bg, Image.new("RGB", (W, H), P.BG), 0.35)


def _frame(P, W, H, src, kicker, source, area_top, area_bot):
    from PIL import Image, ImageDraw
    im = _cover_bg(P, src, W, H)
    d = ImageDraw.Draw(im)
    top = 170 if H > 1500 else 0
    d.rounded_rectangle([64, top + 62, 114, top + 112], 13, fill=P.ACC)
    d.text((89, top + 87), "GA", font=P._font("black", 21), fill=P.BG, anchor="mm")
    d.text((130, top + 64), P.BRAND, font=P._font("black", 24), fill=P.FG)
    d.text((130, top + 92), f"{P.HANDLE} · Grand Archive TCG", font=P._font("reg", 18), fill=P.MUTED)
    if P.LOGO is not None:
        im.paste(P.LOGO, (W - 64 - P.LOGO.width, top + 42), P.LOGO)
    ky = top + 170
    f = P._font("black", 30)
    tw = d.textlength(kicker.upper(), font=f)
    d.rounded_rectangle([64, ky, 64 + tw + 40, ky + 54], 27, fill=P.ACC)
    d.text((84, ky + 27), kicker.upper(), font=f, fill=P.BG, anchor="lm")
    # immagine
    box_w, box_t, box_b = W - 80, ky + 54 + 40, H - area_bot
    s = min(box_w / src.width, (box_b - box_t) / src.height)
    img = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    x, y = (W - img.width) // 2, box_t + (box_b - box_t - img.height) // 2
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], 22, fill=255)
    d.rounded_rectangle([x - 3, y - 3, x + img.width + 2, y + img.height + 2], 25, outline=P.LINE, width=3)
    im.paste(img, (x, y), mask)
    # piede
    fy = H - area_bot + 40 if H > 1500 else H - 116
    d.line([(64, fy), (W - 64, fy)], fill=P.LINE, width=2)
    d.text((64, fy + 22), f"Source: {source}", font=P._font("reg", 22), fill=P.MUTED)
    d.text((64, fy + 54), "Card images © Weebs of the Shore", font=P._font("reg", 22), fill=P.MUTED)
    d.text((W - 64, fy + 22), P.HANDLE, font=P._font("bold", 24), fill=P.ACC, anchor="ra")
    return im


def render(work, man):
    from PIL import Image
    P = _pipeline()
    try:
        P.load_season_logo(work, {"season": man.get("season", ".asphodel/paradise")})
    except Exception as e:  # noqa: BLE001
        print("logo stagione non disponibile:", e, file=sys.stderr)
    for it in man["items"]:
        it["stories"], it["posts"] = [], []
        for n, f in enumerate(it["images"], 1):
            src = Image.open(f).convert("RGB")
            st = _frame(P, ST_W, ST_H, src, it.get("kicker") or "News", it["source"], 0, 400)
            out = os.path.join(work, f"{it['id']}-{n}-story.jpg")
            st.save(out, quality=90)
            it["stories"].append(os.path.basename(out))
            if it.get("post"):
                po = _frame(P, P.SW, P.SH, src, it.get("kicker") or "News", it["source"], 0, 130)
                out = os.path.join(work, f"{it['id']}-{n}-post.jpg")
                po.save(out, quality=90)
                it["posts"].append(os.path.basename(out))
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
