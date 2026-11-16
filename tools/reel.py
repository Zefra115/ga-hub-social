#!/usr/bin/env python3
"""Reel del Meta Report (1080x1920, 30 fps, ~18 s, senza audio: la musica si aggiunge dall'app).

  python3 -I tools/reel.py --spec reels/2026-11-16.json --out reel.mp4 [--work DIR] [--preview]

Scene (spec JSON, testi in inglese come le altre grafiche del meta report):
  hook    → titolo d'impatto, spirit + champion più alto dell'archetipo in crescita, percentuale che sale
  top3    → i 3 archetipi più giocati con barre animate
  movers  → chi sale / chi scende (15 giorni)
  event   → evento più grande: spirit e champion più alto della lista vincitrice girati dal dorso GA HUB
  cta     → logo, "full report in our latest post", follow
Zone sicure dei reel: contenuti tra y≈260 e y≈1500 e lontani dal bordo destro (pulsanti).
"""
import argparse, importlib.util, json, math, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W, H, FPS = 1080, 1920, 30


def _pipeline():
    spec = importlib.util.spec_from_file_location("gapipe", os.path.join(HERE, "pipeline.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = _pipeline()


def ease(t):  # ease-out cubic
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def prog(t, start, dur=0.45):
    return ease((t - start) / dur)


def emoji(ch, size):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)
    im = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 0), ch, font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    return im.resize((int(im.width * size / im.height), size), Image.LANCZOS)


class Frame:
    def __init__(self, base):
        from PIL import Image, ImageDraw
        self.im = base.copy()
        self.Image, self.ImageDraw = Image, ImageDraw

    def layer(self, alpha, dx=0, dy=0):
        """Contesto per disegnare un elemento con opacità e spostamento."""
        return _Layer(self, alpha, dx, dy)


class _Layer:
    def __init__(self, fr, alpha, dx, dy):
        self.fr, self.alpha, self.dx, self.dy = fr, alpha, int(dx), int(dy)
        self.l = fr.Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.d = fr.ImageDraw.Draw(self.l)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        if self.alpha <= 0.01:
            return
        l = self.l
        if self.dx or self.dy:
            l2 = self.fr.Image.new("RGBA", (W, H), (0, 0, 0, 0))
            l2.paste(l, (self.dx, self.dy), l)
            l = l2
        if self.alpha < 0.999:
            a = l.getchannel("A").point(lambda v: int(v * self.alpha))
            l.putalpha(a)
        self.fr.im.paste(l, (0, 0), l)


def background(t, logo_img):
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGB", (W, H), P.BG)
    glow = Image.new("L", (W, H), 0)
    gx = W * (0.3 + 0.4 * math.sin(t * 0.35))
    gy = H * (0.35 + 0.1 * math.cos(t * 0.27))
    ImageDraw.Draw(glow).ellipse([gx - 520, gy - 520, gx + 520, gy + 520], fill=70)
    im.paste(Image.new("RGB", (W, H), P.ACC), (0, 0), glow.filter(ImageFilter.GaussianBlur(160)))
    d = ImageDraw.Draw(im)
    top = 150
    if logo_img is not None:
        lg = logo_img.resize((84, 84), Image.LANCZOS)
        m = Image.new("L", (84, 84), 0)
        ImageDraw.Draw(m).ellipse([0, 0, 83, 83], fill=255)
        im.paste(lg, (64, top), m)
    d.text((166, top + 8), P.BRAND, font=P._font("black", 34), fill=P.FG)
    d.text((166, top + 50), f"{P.HANDLE} · Grand Archive TCG", font=P._font("reg", 24), fill=P.MUTED)
    if P.LOGO is not None:
        im.paste(P.LOGO, (W - 64 - P.LOGO.width, top - 2), P.LOGO)
    return im


def text_c(d, xy, s, font, fill, anchor="mm"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def wrap(d, s, f, w):
    return P._wrap(d, s, f, w)


def el_color(name):
    for k, c in P.ELC.items():
        if name.startswith(k):
            return c
    return P.ACC


def fmt(v, dec=1, suffix="%"):
    return f"{v:.{dec}f}{suffix}"


# ------------------------------------------------------------------ scene
def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


_CARD_CACHE = {}


def card_img(name, edition, work):
    key = (name, edition)
    if key not in _CARD_CACHE:
        spec = importlib.util.spec_from_file_location("garulings", os.path.join(HERE, "rulings.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _CARD_CACHE[key] = m.card_image(name, edition, os.path.join(work, "cards")).convert("RGBA")
    return _CARD_CACHE[key]


def back_img():
    from PIL import Image
    if "back" not in _CARD_CACHE:
        _CARD_CACHE["back"] = Image.open(os.path.join(ROOT, "assets/brand/dorso-GA-HUB.png")).convert("RGBA")
    return _CARD_CACHE["back"]


def put_card(L, img, cx, cy, h, angle=0.0, sx=1.0, glow=None):
    """Disegna una carta centrata in (cx, cy), alta h, ruotata e schiacciata in orizzontale (per il flip)."""
    from PIL import Image, ImageDraw, ImageFilter
    w = int(img.width * h / img.height)
    ww = max(2, int(w * abs(sx)))
    c = img.resize((ww, h), Image.LANCZOS)
    m = Image.new("L", (ww, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, ww - 1, h - 1], int(w * 0.045), fill=255)
    c.putalpha(m)
    pad = 60
    canvas = Image.new("RGBA", (ww + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([pad + 6, pad + 18, pad + ww + 6, pad + h + 18], 24, fill=170)
    canvas.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 255)), (0, 0), sh.filter(ImageFilter.GaussianBlur(16)))
    if glow:
        gl = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(gl).rounded_rectangle([pad - 8, pad - 8, pad + ww + 8, pad + h + 8], 30, fill=150)
        canvas.paste(Image.new("RGBA", canvas.size, glow + (255,)), (0, 0), gl.filter(ImageFilter.GaussianBlur(22)))
    canvas.paste(c, (pad, pad), c)
    if angle:
        canvas = canvas.rotate(angle, resample=Image.BICUBIC, expand=True)
    L.l.paste(canvas, (int(cx - canvas.width / 2), int(cy - canvas.height / 2)), canvas)


def scene_hook(fr, t, s, work):
    with fr.layer(prog(t, .1, .35), dy=(1 - prog(t, .1, .35)) * 40) as L:
        text_c(L.d, (W // 2, 330), s["kicker"].upper(), P._font("semi", 34), P.ACC)
    with fr.layer(prog(t, .25, .4), dy=(1 - prog(t, .25, .4)) * 60) as L:
        f = P._font("black", 82)
        y = 420
        for ln in wrap(L.d, s["title"], f, W - 160):
            text_c(L.d, (W // 2, y), ln, f, P.FG)
            y += 96
    # carte: spirit e champion dell'archetipo, "servite" con rimbalzo
    cards = s.get("cards", [])
    h = 520
    poses = [(W // 2 - 175, 900, 9), (W // 2 + 175, 900, -7)] if len(cards) == 2 else [(W // 2, 900, 0)]
    col = el_color(s.get("element", ""))
    for i, (c, (cx, cy, ang)) in enumerate(zip(cards, poses)):
        st = .55 + i * .2
        k = ease_back((t - st) / .55)
        if t < st:
            continue
        with fr.layer(min(1, (t - st) / .2)) as L:
            put_card(L, card_img(c["name"], c.get("edition"), work), cx, cy + (1 - k) * 700, h,
                     angle=ang * k + (1 - k) * (25 if i else -25), glow=col if i == len(cards) - 1 else None)
            if c.get("label") and k > .9:
                text_c(L.d, (cx, cy + h // 2 + 40), c["label"].upper(), P._font("semi", 28), P.MUTED)
    # percentuale che cresce, sopra le carte in basso
    k = prog(t, 1.25, 1.2)
    v = s["from"] + (s["to"] - s["from"]) * k
    a = prog(t, 1.15, .3)
    with fr.layer(a, dy=(1 - a) * 50) as L:
        d = L.d
        bw, by = 720, 1240
        d.rounded_rectangle([W // 2 - bw // 2, by, W // 2 + bw // 2, by + 230], 40, fill=(13, 15, 23, 235), outline=col + (255,), width=4)
        txt = f"{fmt(s['from'])} → "
        f1, f2 = P._font("bold", 52), P._font("black", 150)
        w1, w2 = d.textlength(txt, font=f1), d.textlength(fmt(v), font=f2)
        x0 = W // 2 - (w1 + w2) / 2
        d.text((x0, by + 110), txt, font=f1, fill=P.MUTED, anchor="lm")
        d.text((x0 + w1, by + 108), fmt(v), font=f2, fill=col, anchor="lm")
        text_c(d, (W // 2, by + 200), s["sub"], P._font("semi", 32), P.FG)
    if t > 2.45:
        e = emoji(s.get("emoji", "🚀"), 110)
        a = ease_back((t - 2.45) / .4)
        with fr.layer(min(1, (t - 2.45) / .15)) as L:
            L.l.paste(e, (W // 2 + 300, int(1190 - 40 * a)), e)


def scene_top3(fr, t, s):
    with fr.layer(prog(t, 0, .35)) as L:
        L.d.text((64, 330), s["kicker"].upper(), font=P._font("semi", 34), fill=P.ACC)
        L.d.text((64, 380), s["title"], font=P._font("black", 76), fill=P.FG)
    medals = ["🥇", "🥈", "🥉"]
    maxv = max(r["share"] for r in s["rows"])
    for i, r in enumerate(s["rows"]):
        st = .45 + i * .55
        a = prog(t, st, .4)
        y = 560 + i * 300
        with fr.layer(a, dx=(1 - a) * 300) as L:
            d = L.d
            d.rounded_rectangle([64, y, W - 64, y + 250], 28, fill=P.SURF + (255,), outline=P.LINE + (255,), width=2)
            m = emoji(medals[i], 76)
            L.l.paste(m, (96, y + 30), m)
            col = el_color(r["name"])
            name_f = P._font("bold", 44)
            lines = wrap(d, r["name"], name_f, W - 96 - 200 - 230)
            ny = y + 36
            for ln in lines[:2]:
                d.text((200, ny), ln, font=name_f, fill=P.FG)
                ny += 52
            bw = int((W - 128 - 136 - 220) * r["share"] / maxv * prog(t, st + .2, .7))
            by = y + 175
            d.rounded_rectangle([200, by, 200 + max(bw, 12), by + 26], 13, fill=col + (255,))
            d.text((W - 96, y + 150), fmt(r["share"] * prog(t, st + .2, .7)), font=P._font("black", 64), fill=P.FG, anchor="ra")
            d.text((W - 96, y + 40), f"WR {fmt(r['wr'])}", font=P._font("semi", 30), fill=P.MUTED, anchor="ra")


def scene_movers(fr, t, s):
    with fr.layer(prog(t, 0, .35)) as L:
        L.d.text((64, 330), s["kicker"].upper(), font=P._font("semi", 34), fill=P.ACC)
        L.d.text((64, 380), s["title"], font=P._font("black", 76), fill=P.FG)
    blocks = [("RISING", s["up"], P.GOOD, "▲"), ("FALLING", s["down"], P.BAD, "▼")]
    y0 = 540
    for bi, (lab, rows, col, arrow) in enumerate(blocks):
        st = .3 + bi * 1.3
        with fr.layer(prog(t, st, .35)) as L:
            L.d.text((64, y0), lab, font=P._font("black", 44), fill=col)
        for i, r in enumerate(rows):
            a = prog(t, st + .25 + i * .22, .35)
            y = y0 + 70 + i * 118
            with fr.layer(a, dx=(1 - a) * 200) as L:
                d = L.d
                d.rounded_rectangle([64, y, W - 64, y + 100], 22, fill=P.SURF + (255,), outline=P.LINE + (255,), width=2)
                d.ellipse([92, y + 38, 116, y + 62], fill=el_color(r["name"]) + (255,))
                f = P._font("bold", 36)
                nm = r["name"]
                while d.textlength(nm, font=f) > W - 64 - 140 - 250:
                    nm = nm[:-2] + "…"
                d.text((140, y + 50), nm, font=f, fill=P.FG, anchor="lm")
                d.text((W - 96, y + 50), f"{arrow} {r['delta']:+.1f}".replace("+-", "-"), font=P._font("black", 42), fill=col, anchor="rm")
        y0 += 70 + len(rows) * 118 + 60


def scene_event(fr, t, s, work):
    with fr.layer(prog(t, .05, .35)) as L:
        L.d.text((64, 330), s["kicker"].upper(), font=P._font("semi", 34), fill=P.ACC)
        L.d.text((64, 380), s["event"], font=P._font("black", 72), fill=P.FG)
        L.d.text((64, 470), s["detail"], font=P._font("semi", 36), fill=P.MUTED)
    # carte coperte (dorso GA HUB) che arrivano e si girano
    cards = s.get("cards", [])
    h = 470
    poses = [(W // 2 - 190, 820, 6), (W // 2 + 190, 820, -6)] if len(cards) == 2 else [(W // 2, 820, 0)]
    col = el_color(s["deck"])
    for i, (c, (cx, cy, ang)) in enumerate(zip(cards, poses)):
        st = .3 + i * .18
        if t < st:
            continue
        k = ease((t - st) / .45)
        fs = 1.0 + i * .2  # inizio del flip
        if t < fs:
            img, sx = back_img(), 1.0
        else:
            u = min(1.0, (t - fs) / .36)
            if u < .5:
                img, sx = back_img(), 1 - u * 2
            else:
                img, sx = card_img(c["name"], c.get("edition"), work), (u - .5) * 2
        with fr.layer(min(1, (t - st) / .15)) as L:
            put_card(L, img, cx + (1 - k) * (-500 if i == 0 else 500), cy, h, angle=ang * k, sx=sx,
                     glow=col if (t > fs + .36 and i == len(cards) - 1) else None)
            if c.get("label") and t > fs + .36:
                text_c(L.d, (cx, cy + h // 2 + 40), c["label"].upper(), P._font("semi", 28), P.MUTED)
    a = prog(t, 1.75, .4)
    with fr.layer(a, dy=(1 - a) * 60) as L:
        d = L.d
        d.rounded_rectangle([64, 1150, W - 64, 1440], 28, fill=(23, 27, 40, 240), outline=P.GOLD + (255,), width=3)
        tr = emoji("🏆", 64)
        L.l.paste(tr, (100, 1180), tr)
        d.text((186, 1192), "WINNER", font=P._font("semi", 30), fill=P.GOLD)
        d.text((100, 1262), s["winner"], font=P._font("black", 56), fill=P.FG)
        f = P._font("bold", 40)
        y = 1345
        for ln in wrap(d, s["deck"], f, W - 200)[:2]:
            d.text((100, y), ln, font=f, fill=col)
            y += 50


def scene_cta(fr, t, s, logo_img):
    from PIL import Image, ImageDraw
    a = prog(t, 0, .45)
    if logo_img is not None:
        sz = int(420 * (0.85 + 0.15 * a))
        lg = logo_img.resize((sz, sz), Image.LANCZOS)
        m = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(m).ellipse([0, 0, sz - 1, sz - 1], fill=255)
        with fr.layer(a) as L:
            L.l.paste(lg.convert("RGBA"), (W // 2 - sz // 2, 520 - sz // 2 + 200), m)
    with fr.layer(prog(t, .35, .4), dy=(1 - prog(t, .35, .4)) * 40) as L:
        f = P._font("black", 66)
        y = 1050
        for ln in wrap(L.d, s["title"], f, W - 160):
            text_c(L.d, (W // 2, y), ln, f, P.FG)
            y += 78
        text_c(L.d, (W // 2, y + 30), s["sub"], P._font("semi", 38), P.MUTED)
    a2 = prog(t, .8, .4)
    with fr.layer(a2) as L:
        pulse = 1 + 0.03 * math.sin(t * 6)
        bw, bh = int(620 * pulse), int(110 * pulse)
        L.d.rounded_rectangle([W // 2 - bw // 2, 1390 - bh // 2, W // 2 + bw // 2, 1390 + bh // 2], bh // 2, fill=P.ACC + (255,))
        text_c(L.d, (W // 2, 1390), s["button"], P._font("black", 44), P.BG)


def footer(fr, s):
    with fr.layer(1) as L:
        L.d.rectangle([0, 1535, W, 1610], fill=P.BG + (215,))
        L.d.text((64, 1560), s, font=P._font("reg", 24), fill=P.MUTED)


# ------------------------------------------------------------------ montaggio
def render(spec, out, work, preview=False):
    from PIL import Image
    os.makedirs(work, exist_ok=True)
    try:
        P.load_season_logo(work, {"season": spec.get("season", ".asphodel/paradise")})
    except Exception as e:  # noqa: BLE001
        print("logo stagione non disponibile:", e, file=sys.stderr)
    logo_img = Image.open(os.path.join(ROOT, spec.get("logo", "assets/brand/logo-GA-HUB.png"))).convert("RGB")
    scenes = spec["scenes"]
    frames_dir = os.path.join(work, "frames")
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir)
    n = 0
    thumbs = []
    for sc in scenes:
        dur = sc["dur"]
        nf = int(dur * FPS)
        for i in range(nf):
            t = i / FPS
            gt = n / FPS
            fr = Frame(background(gt, logo_img))
            kind = sc["type"]
            if kind == "hook":
                scene_hook(fr, t, sc, work)
            elif kind == "top3":
                scene_top3(fr, t, sc)
            elif kind == "movers":
                scene_movers(fr, t, sc)
            elif kind == "event":
                scene_event(fr, t, sc, work)
            elif kind == "cta":
                scene_cta(fr, t, sc, logo_img)
            footer(fr, spec.get("footer", "Data: grandarchivestats.com · Card images © Weebs of the Shore"))
            # dissolvenza in uscita (tranne l'ultima scena)
            if sc is not scenes[-1] and t > dur - 0.2:
                k = (t - (dur - 0.2)) / 0.2
                fr.im = Image.blend(fr.im, background(gt, logo_img), k)
            fr.im.save(os.path.join(frames_dir, f"f{n:05d}.jpg"), quality=92)
            if i == nf - 8:
                thumbs.append(fr.im.copy())
            n += 1
    # anteprima: un fotogramma per scena
    sheet = Image.new("RGB", (len(thumbs) * 370, 660), (255, 255, 255))
    for i, th in enumerate(thumbs):
        sheet.paste(th.resize((360, 640)), (i * 370, 10))
    sheet.save(os.path.join(work, "preview.jpg"), quality=88)
    if preview:
        print("anteprima:", os.path.join(work, "preview.jpg"))
        return
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(frames_dir, "f%05d.jpg"),
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-shortest",
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    # copertina del reel (fotogramma dell'hook)
    Image.open(os.path.join(frames_dir, f"f{int(scenes[0]['dur'] * FPS) - 8:05d}.jpg")).save(os.path.splitext(out)[0] + "-cover.jpg", quality=92)
    print(json.dumps({"video": out, "seconds": n / FPS, "frames": n, "preview": os.path.join(work, "preview.jpg")}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    render(spec, a.out, a.work or os.path.splitext(a.out)[0] + "_work", a.preview)


if __name__ == "__main__":
    main()
