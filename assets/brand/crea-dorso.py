# Crea il dorso del logo GA HUB: targa ridisegnata (stile del dorso) con "GA" e "HUB" in Cinzel Black
# (font OFL: https://github.com/google/fonts/tree/main/ofl/cinzel). Uso:
#   python3 -I crea-dorso.py <dorso.jpg> <cartella con fonts/Cinzel.ttf> <uscita.png>
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
src_path, S = sys.argv[1], sys.argv[2]
K = 3
src = Image.open(src_path).convert('RGB')
big = src.resize((src.width*K, src.height*K), Image.LANCZOS)
W, H = big.size

def cinzel(size):
    f = ImageFont.truetype(f'{S}/fonts/Cinzel.ttf', size); f.set_variation_by_name('Black'); return f

def plate_poly(l, t, r, b, c, tip):
    m = (t+b)/2
    return [(l+c, t), (r-c, t), (r, t+c), (r, m-tip), (r+tip, m), (r, m+tip), (r, b-c), (r-c, b),
            (l+c, b), (l, b-c), (l, m+tip), (l-tip, m), (l, m-tip), (l, t+c)]

def inset(pts, cx, cy, k):
    return [(cx+(x-cx)*k, cy+(y-cy)*k) for x, y in pts]

cx = W/2
l, t, r, b = 36*K, 168*K, W-36*K, 392*K
cy = (t+b)/2
outer = plate_poly(l, t, r, b, 18*K, 16*K)
# ombra
sh = Image.new('L', (W, H), 0); ImageDraw.Draw(sh).polygon([(x, y+8*K) for x, y in outer], fill=200)
big.paste(Image.new('RGB', (W, H), (0, 0, 0)), (0, 0), sh.filter(ImageFilter.GaussianBlur(8*K)))
d = ImageDraw.Draw(big)
# bordo argento a più livelli (stile del dorso)
d.polygon(outer, fill=(12, 13, 18))
d.polygon(inset(outer, cx, cy, .985), fill=(186, 194, 210))
d.polygon(inset(outer, cx, cy, .965), fill=(70, 74, 86))
d.polygon(inset(outer, cx, cy, .955), fill=(140, 148, 164))
d.polygon(inset(outer, cx, cy, .94), fill=(24, 25, 32))
# fondo con leggera vignettatura
vig = Image.new('L', (W, H), 0); ImageDraw.Draw(vig).polygon(inset(outer, cx, cy, .94), fill=255)
glow = Image.new('L', (W, H), 0); ImageDraw.Draw(glow).ellipse([cx-120*K, cy-70*K, cx+120*K, cy+70*K], fill=60)
big.paste(Image.new('RGB', (W, H), (60, 66, 92)), (0, 0), ImageChops.multiply(vig, glow.filter(ImageFilter.GaussianBlur(30*K))))
d = ImageDraw.Draw(big)

def gem(x, y, s):
    d.polygon([(x, y-s*1.5), (x+s, y), (x, y+s*1.5), (x-s, y)], fill=(12, 13, 18))
    d.polygon([(x, y-s*1.25), (x+s*.8, y), (x, y+s*1.25), (x-s*.8, y)], fill=(186, 194, 210))
    d.polygon([(x, y-s), (x+s*.6, y), (x, y+s), (x-s*.6, y)], fill=(40, 200, 230))
    d.polygon([(x, y-s), (x+s*.6, y), (x, y)], fill=(150, 240, 255))
gem(cx, t, 9*K); gem(cx, b, 9*K)
gem(l-16*K, cy, 6*K); gem(r+16*K, cy, 6*K)

def styled(text, font, cx, cy, spacing, top_c, mid_c, bot_c, inner_w, outer_w):
    global big
    d = ImageDraw.Draw(big)
    ws = [d.textlength(ch, font=font) for ch in text]
    tw = sum(ws) + spacing*(len(text)-1)
    mask = Image.new('L', (W, H), 0); md = ImageDraw.Draw(mask)
    x = cx - tw/2
    for ch, w in zip(text, ws):
        md.text((x, cy), ch, font=font, fill=255, anchor='lm'); x += w + spacing
    bb = mask.getbbox()
    o2 = mask.filter(ImageFilter.MaxFilter(2*(inner_w+outer_w)+1))
    o1 = mask.filter(ImageFilter.MaxFilter(2*inner_w+1))
    big.paste(Image.new('RGB', (W, H), (0, 0, 0)), (0, 8), o2.filter(ImageFilter.GaussianBlur(8)))
    big.paste(Image.new('RGB', (W, H), (8, 16, 34)), (0, 0), o2)
    big.paste(Image.new('RGB', (W, H), (236, 246, 255)), (0, 0), o1)
    h = bb[3]-bb[1]; g = Image.new('RGB', (1, h))
    for y in range(h):
        tt = y/max(1, h-1)
        a, c2, u = (top_c, mid_c, tt*2) if tt < .5 else (mid_c, bot_c, (tt-.5)*2)
        g.putpixel((0, y), tuple(int(a[i]+(c2[i]-a[i])*u) for i in range(3)))
    layer = Image.new('RGB', (W, H)); layer.paste(g.resize((W, h)), (0, bb[1]))
    big.paste(layer, (0, 0), mask.filter(ImageFilter.MinFilter(3)))
    return bb

bb = styled('GA', cinzel(170*K), cx, 250*K, 4*K, (205, 242, 255), (70, 160, 240), (18, 76, 186), 5, 9)
# separatore
d = ImageDraw.Draw(big)
sy = 309*K
d.line([(cx-110*K, sy), (cx-14*K, sy)], fill=(140, 148, 164), width=2*K)
d.line([(cx+14*K, sy), (cx+110*K, sy)], fill=(140, 148, 164), width=2*K)
gem(cx, sy, 4*K)
styled('HUB', cinzel(62*K), cx, 356*K, 10*K, (215, 245, 255), (90, 175, 245), (30, 110, 215), 3, 6)
big.save(sys.argv[3])
