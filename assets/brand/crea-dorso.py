# Crea i dorsi del logo: copre GRAND ARCHIVE con "GA" (font Cinzel Black, OFL: https://github.com/google/fonts/tree/main/ofl/cinzel)
# e aggiunge la targa HUB. Uso: python3 -I crea-dorso.py <cartella-immagini> <cartella-lavoro-con-fonts/Cinzel.ttf> [dorso.jpg]
import sys, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
B, S = sys.argv[1], sys.argv[2]
K = 3
src = Image.open(sys.argv[3] if len(sys.argv) > 3 else f'{B}/images/1.jpg').convert('RGB')
big = src.resize((src.width*K, src.height*K), Image.LANCZOS)
W, H = big.size

def cinzel(size):
    f = ImageFont.truetype(f'{S}/fonts/Cinzel.ttf', size)
    f.set_variation_by_name('Black')
    return f

# 1) copre GRAND ARCHIVE + Trading Card Game con il fondo scuro della targa (con un po' di grana)
fill = Image.new('RGB', (W, H), (33, 34, 41))
random.seed(1)
nd = ImageDraw.Draw(fill)
for _ in range(60000):
    x, y = random.randrange(W), random.randrange(H)
    v = random.randint(-7, 7)
    nd.point((x, y), fill=(33+v, 34+v, 41+v))
fill = fill.filter(ImageFilter.GaussianBlur(1.2))
m = Image.new('L', (W, H), 0)
ImageDraw.Draw(m).rounded_rectangle([47*K, 178*K, 331*K, 322*K], 18*K, fill=255)
big.paste(fill, (0, 0), m.filter(ImageFilter.GaussianBlur(6*K)))

def styled(text, font, cx, cy, spacing, grad_top, grad_bot, inner=(236, 246, 255), outer=(8, 16, 34), inner_w=4, outer_w=9):
    global big
    d = ImageDraw.Draw(big)
    ws = [d.textlength(c, font=font) for c in text]
    tw = sum(ws) + spacing*(len(text)-1)
    mask = Image.new('L', (W, H), 0); md = ImageDraw.Draw(mask)
    x = cx - tw/2
    for c, w in zip(text, ws):
        md.text((x, cy), c, font=font, fill=255, anchor='lm'); x += w + spacing
    bb = mask.getbbox()
    o2 = mask.filter(ImageFilter.MaxFilter(2*(inner_w+outer_w)+1))
    o1 = mask.filter(ImageFilter.MaxFilter(2*inner_w+1))
    sh = o2.filter(ImageFilter.GaussianBlur(10))
    big.paste(Image.new('RGB', (W, H), (0, 0, 0)), (0, 10), sh)
    big.paste(Image.new('RGB', (W, H), outer), (0, 0), o2)
    big.paste(Image.new('RGB', (W, H), inner), (0, 0), o1)
    h = bb[3]-bb[1]
    g = Image.new('RGB', (1, h))
    for y in range(h):
        t = y/max(1, h-1)
        mid = (70, 160, 240)
        if t < .5:
            c = tuple(int(grad_top[i]+(mid[i]-grad_top[i])*t*2) for i in range(3))
        else:
            c = tuple(int(mid[i]+(grad_bot[i]-mid[i])*(t-.5)*2) for i in range(3))
        g.putpixel((0, y), c)
    layer = Image.new('RGB', (W, H)); layer.paste(g.resize((W, h)), (0, bb[1]))
    big.paste(layer, (0, 0), mask.filter(ImageFilter.MinFilter(3)))
    return bb

cx = 189*K
styled('GA', cinzel(118*K), cx, 240*K, 2*K, (200, 240, 255), (20, 80, 190), inner_w=4, outer_w=7)
big.save(f'{S}/back-ga.png')
# 2) targa HUB sotto
top, h, w = 314*K, 54*K, 150*K
pl = Image.new('RGBA', (W, H), (0, 0, 0, 0))
ImageDraw.Draw(pl).rounded_rectangle([cx-w//2-4*K, top-4*K, cx+w//2+4*K, top+h+4*K], 14*K, fill=(10, 12, 18, 170))
pl = pl.filter(ImageFilter.GaussianBlur(4*K)); big.paste(pl, (0, 0), pl)
d = ImageDraw.Draw(big)
d.rounded_rectangle([cx-w//2, top, cx+w//2, top+h], 12*K, fill=(24, 26, 34), outline=(176, 186, 204), width=2*K)
d.rounded_rectangle([cx-w//2+5*K, top+5*K, cx+w//2-5*K, top+h-5*K], 9*K, outline=(90, 98, 112), width=1*K)
styled('HUB', cinzel(40*K), cx, top+h//2+2*K, 5*K, (190, 235, 255), (40, 130, 225), inner_w=2, outer_w=4)
big.save(f'{S}/back-hub.png')
big.crop((30*K, 150*K, 350*K, 390*K)).save(f'{S}/back-hub-zoom.png')
