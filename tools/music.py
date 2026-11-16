#!/usr/bin/env python3
"""Base musicale originale per i reel GA.Hub, sintetizzata da zero (nessun campione, nessuna licenza).

  python3 -I tools/music.py --style dubstep --bpm 140 --sections 2,3,3,3,2 --out assets/music/dubstep.wav
  python3 -I tools/music.py --style epic --bars 10 --bpm 120 --out assets/music/reel-base.wav

--sections: battute di ogni scena del reel; all'inizio di ogni scena c'è un impatto (preceduto da un riser).

Stile "dubstep" (predefinito): mezzo tempo (cassa sull'1, rullante sul 3), basso wobble con filtro
modulato a velocità diverse (1/4, 1/8, terzine, 1/16), sub-basso sinusoidale, distorsione, pad scuro
molto basso, niente melodia. Fa minore.

Stile "epic" (versione precedente):
120 BPM, 2 battute = 4 s = una scena del reel: ogni cambio di scena cade su un impatto (boom + piatto),
preceduto da un "riser". Re minore, progressione epica (Dm Bb F C | Dm Bb Gm A), cassa dritta,
clap su 2 e 4, hi-hat in sedicesimi, basso pulsante con sidechain, pad supersaw, arpeggio e una
melodia "eroica" nelle scene centrali. Ultima battuta: impatto finale che sfuma.
"""
import argparse, wave
import numpy as np

SR = 48000


def t_arr(sec):
    return np.arange(int(sec * SR)) / SR


def lowpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def highpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (cutoff / np.maximum(f, 1e-3)) ** 4)
    return np.fft.irfft(X, len(x))


def saw(freq, t, harmonics=None):
    n = harmonics or max(1, int((SR / 2) / freq))
    n = min(n, 40)
    out = np.zeros_like(t)
    for k in range(1, n + 1):
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out * (2 / np.pi)


def env_ad(n, a, d):
    e = np.ones(n)
    na = max(1, int(a * SR))
    e[:na] = np.linspace(0, 1, na)
    nd = int(d * SR)
    if nd > 0:
        tail = np.exp(-np.arange(n - na) / max(1, nd) * 5)
        e[na:] = tail[: n - na]
    return e


NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}


def hz(name, octave):
    return 440.0 * 2 ** ((NOTE[name] + 12 * (octave + 1) - 69) / 12)


CHORDS = {  # radice, terza, quinta
    "Dm": ("D", "F", "A"), "Bb": ("Bb", "D", "F"), "F": ("F", "A", "C"), "C": ("C", "E", "G"),
    "Gm": ("G", "Bb", "D"), "A": ("A", "C#", "E"),
}
PROG = ["Dm", "Bb", "F", "C", "Dm", "Bb", "Gm", "A"]


def render(bars=10, bpm=120, seed=1):
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = 4 * beat
    total = bars * bar
    n = int(total * SR)
    L = np.zeros(n)
    R = np.zeros(n)

    def add(sig, start, gain=1.0, pan=0.0):
        i0 = int(start * SR)
        if i0 >= n:
            return
        sig = sig[: n - i0]
        L[i0:i0 + len(sig)] += sig * gain * (1 - max(0, pan))
        R[i0:i0 + len(sig)] += sig * gain * (1 + min(0, pan))

    # --- batteria
    tk = t_arr(0.45)
    f_k = 45 + 110 * np.exp(-tk * 28)
    kick = np.sin(2 * np.pi * np.cumsum(f_k) / SR) * np.exp(-tk * 7.5)
    kick += 0.3 * np.exp(-tk * 120) * rng.uniform(-1, 1, len(tk))
    tc = t_arr(0.25)
    clap = highpass(rng.uniform(-1, 1, len(tc)), 900) * np.exp(-tc * 22)
    clap += 0.35 * np.sin(2 * np.pi * 190 * tc) * np.exp(-tc * 30)
    th = t_arr(0.06)
    hat = highpass(rng.uniform(-1, 1, len(th)), 7000) * np.exp(-th * 70)
    tcr = t_arr(2.5)
    crash = highpass(rng.uniform(-1, 1, len(tcr)), 4500) * np.exp(-tcr * 2.2)
    tb = t_arr(2.0)
    boom = np.sin(2 * np.pi * (38 + 40 * np.exp(-tb * 6)) * tb) * np.exp(-tb * 2.2)
    sidechain = np.ones(n)
    last = bars - 1
    for b in range(bars):
        for q in range(4):
            st = b * bar + q * beat
            if b == last and q > 0:
                continue  # ultima battuta: solo l'impatto finale
            add(kick, st, 0.95)
            i0 = int(st * SR)
            dur = int(0.22 * SR)
            sc = 1 - 0.75 * np.exp(-np.arange(dur) / (0.06 * SR))
            sidechain[i0:i0 + dur] = np.minimum(sidechain[i0:i0 + dur], sc[: max(0, min(dur, n - i0))])
            if q in (1, 3):
                add(clap, st, 0.55)
            for s16 in range(4):
                add(hat, st + s16 * beat / 4, 0.16 if s16 % 2 else 0.09, pan=0.3 if s16 % 2 else -0.3)
    # impatti all'inizio di ogni scena (ogni 2 battute) e riser prima
    for b in range(0, bars, 2):
        st = b * bar
        add(boom, st, 0.9)
        add(crash, st, 0.33, pan=-0.2)
        add(crash, st + 0.012, 0.33, pan=0.2)
        if b > 0:
            rl = beat * 2
            tr = t_arr(rl)
            noise = rng.uniform(-1, 1, len(tr))
            riser = np.zeros_like(tr)
            seg = len(tr) // 8
            for k in range(8):  # rumore che si apre in frequenza
                part = noise[k * seg:(k + 1) * seg]
                riser[k * seg:(k + 1) * seg] = highpass(part, 300 + 900 * k) if len(part) else part
            riser *= (tr / rl) ** 2
            add(riser, st - rl, 0.22)
    add(boom, last * bar, 1.0)
    add(crash, last * bar, 0.45)

    # --- armonia (basso, pad, arpeggio)
    bass = np.zeros(n)
    pad_l, pad_r = np.zeros(n), np.zeros(n)
    arp = np.zeros(n)
    for b in range(bars):
        ch = CHORDS[PROG[b % len(PROG)]] if b < last else CHORDS["Dm"]
        st = b * bar
        # basso: crome sulla radice
        for e in range(8 if b < last else 1):
            tt = t_arr(beat / 2 if b < last else bar * 0.9)
            f0 = hz(ch[0], 1)
            sig = (np.sign(np.sin(2 * np.pi * f0 * tt)) * 0.5 + np.sin(2 * np.pi * f0 * tt)) * env_ad(len(tt), 0.005, 0.18 if b < last else 0.8)
            i0 = int((st + e * beat / 2) * SR)
            bass[i0:i0 + len(sig)] += sig[: max(0, n - i0)]
        # pad: supersaw sull'accordo, una battuta
        tt = t_arr(bar)
        e = np.minimum(1, tt / 0.08) * np.minimum(1, (bar - tt) / 0.15)
        for idx, nm in enumerate(ch):
            f0 = hz(nm, 3 if idx else 3)
            for det, side in ((-0.12, 0), (0.0, None), (0.12, 1)):
                s = saw(f0 * 2 ** (det / 12), tt, 12) * e
                i0 = int(st * SR)
                m = min(len(s), n - i0)
                if side is None or side == 0:
                    pad_l[i0:i0 + m] += s[:m]
                if side is None or side == 1:
                    pad_r[i0:i0 + m] += s[:m]
        # arpeggio in sedicesimi (dalla seconda scena)
        if 2 <= b < last:
            pattern = [0, 1, 2, 1, 0, 2, 1, 2]
            for s16 in range(16):
                nm = ch[pattern[s16 % 8]]
                oc = 5 if s16 % 4 != 3 else 6
                tt = t_arr(beat / 4)
                f0 = hz(nm, oc)
                sig = (np.sign(np.sin(2 * np.pi * f0 * tt)) * 0.6 + saw(f0, tt, 8) * 0.4) * env_ad(len(tt), 0.002, 0.05)
                i0 = int((st + s16 * beat / 4) * SR)
                arp[i0:i0 + len(sig)] += sig[: max(0, n - i0)]
    bass = lowpass(bass, 900) * sidechain
    pad_l = lowpass(pad_l, 2600) * sidechain
    pad_r = lowpass(pad_r, 2600) * sidechain
    arp = lowpass(arp, 5000) * (0.6 + 0.4 * sidechain)
    L += bass * 0.32 + pad_l * 0.07 + arp * 0.10
    R += bass * 0.32 + pad_r * 0.07
    # eco dell'arpeggio a destra (croma puntata)
    d = int(beat * 0.75 * SR)
    R[d:] += arp[:-d] * 0.08

    # --- melodia "eroica" (ottoni sintetici) nelle scene 3 e 4
    melody = [  # (battuta, beat, durata in beat, nota, ottava)
        (4, 0, 1.5, "D", 5), (4, 1.5, 0.5, "E", 5), (4, 2, 2, "F", 5),
        (5, 0, 1.5, "F", 5), (5, 1.5, 0.5, "G", 5), (5, 2, 1, "A", 5), (5, 3, 1, "Bb", 5),
        (6, 0, 2, "A", 5), (6, 2, 1, "G", 5), (6, 3, 1, "F", 5),
        (7, 0, 3, "E", 5), (7, 3, 1, "C#", 5),
        (8, 0, 2, "D", 5), (8, 2, 2, "A", 5),
    ]
    lead = np.zeros(n)
    for b, bt, du, nm, oc in melody:
        if b >= last:
            continue
        tt = t_arr(du * beat)
        f0 = hz(nm, oc)
        vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * tt) * np.minimum(1, tt / 0.3)
        ph = 2 * np.pi * np.cumsum(f0 * vib) / SR
        sig = sum(np.sin(ph * k) / k ** 1.2 for k in range(1, 9))
        e = np.minimum(1, tt / 0.04) * np.minimum(1, (du * beat - tt) / 0.06)
        i0 = int((b * bar + bt * beat) * SR)
        lead[i0:i0 + len(sig)] += (sig * e)[: max(0, n - i0)]
    lead = lowpass(lead, 3200)
    L += lead * 0.12
    R += lead * 0.12
    d2 = int(0.11 * SR)
    L[d2:] += lead[:-d2] * 0.04

    # --- master: coda, saturazione morbida, normalizzazione
    fade = int(1.6 * SR)
    L[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    R[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    st = np.stack([L, R], axis=1)
    st = np.tanh(st * 1.4)
    st /= np.max(np.abs(st)) / 0.89
    return st


def fft_convolve(x, ir):
    nfft = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)
    return y[: len(x)]


def render_dubstep(sections=(2, 3, 3, 3, 2), bpm=140, seed=1):
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = 4 * beat
    bars = sum(sections)
    total = bars * bar + 1.2  # coda per l'ultimo impatto
    n = int(total * SR)
    L, R = np.zeros(n), np.zeros(n)
    starts = np.cumsum([0] + list(sections))[:-1]  # battuta d'inizio di ogni scena

    def add(sig, start, gain=1.0, pan=0.0, buf=None):
        i0 = int(start * SR)
        if i0 >= n or i0 + len(sig) <= 0:
            return
        if i0 < 0:
            sig, i0 = sig[-i0:], 0
        sig = sig[: n - i0]
        if buf is not None:
            buf[i0:i0 + len(sig)] += sig * gain
            return
        L[i0:i0 + len(sig)] += sig * gain * (1 - max(0, pan))
        R[i0:i0 + len(sig)] += sig * gain * (1 + min(0, pan))

    # --- suoni di batteria
    tk = t_arr(0.5)
    kick = np.sin(2 * np.pi * np.cumsum(42 + 140 * np.exp(-tk * 30)) / SR) * np.exp(-tk * 6)
    kick += 0.35 * np.exp(-tk * 150) * rng.uniform(-1, 1, len(tk))
    kick = np.tanh(kick * 1.6)
    ts = t_arr(0.6)
    snare = highpass(rng.uniform(-1, 1, len(ts)), 1200) * np.exp(-ts * 14) * 0.9
    snare += np.sin(2 * np.pi * 185 * ts) * np.exp(-ts * 25) * 0.7
    snare += np.sin(2 * np.pi * 330 * ts) * np.exp(-ts * 35) * 0.3
    ir = rng.uniform(-1, 1, int(0.9 * SR)) * np.exp(-np.arange(int(0.9 * SR)) / SR * 6)
    snare_verb = fft_convolve(snare, highpass(ir, 500)) * 0.05
    snare = np.concatenate([snare, np.zeros(len(snare_verb) - len(snare))]) + snare_verb if len(snare_verb) > len(snare) else snare + snare_verb[: len(snare)]
    th = t_arr(0.05)
    hat = highpass(rng.uniform(-1, 1, len(th)), 8000) * np.exp(-th * 90)
    topen = t_arr(0.25)
    ohat = highpass(rng.uniform(-1, 1, len(topen)), 7000) * np.exp(-topen * 14)
    tcr = t_arr(3.0)
    crash = highpass(rng.uniform(-1, 1, len(tcr)), 4000) * np.exp(-tcr * 1.8)
    tb = t_arr(2.5)
    boom = np.tanh(2 * np.sin(2 * np.pi * (32 + 60 * np.exp(-tb * 5)) * tb) * np.exp(-tb * 1.6))

    sidechain = np.ones(n)

    def duck(start, depth=0.85, rel=0.12):
        i0 = int(start * SR)
        d = int(0.35 * SR)
        sc = 1 - depth * np.exp(-np.arange(d) / (rel * SR))
        m = max(0, min(d, n - i0))
        sidechain[i0:i0 + m] = np.minimum(sidechain[i0:i0 + m], sc[:m])

    # pattern di mezzo tempo (in sedicesimi): cassa 0 e 10, rullante 8, hat in crome con rullate
    for b in range(bars):
        st = b * bar
        add(kick, st, 1.0); duck(st)
        if b % 2 == 1:
            add(kick, st + 10 * beat / 4, 0.85); duck(st + 10 * beat / 4, .7)
        else:
            add(kick, st + 11 * beat / 4, 0.75); duck(st + 11 * beat / 4, .6)
        add(snare, st + 2 * beat, 0.75)
        for e in range(8):
            add(hat, st + e * beat / 2, 0.13 if e % 2 else 0.08, pan=0.25 if e % 2 else -0.25)
        add(ohat, st + 3.5 * beat, 0.08, pan=0.3)
        if b % 3 == 2:  # rullata di hat in terzine a fine battuta
            for k in range(6):
                add(hat, st + 3 * beat + k * beat / 6, 0.07 + 0.015 * k, pan=-0.2 + 0.08 * k)

    # impatti e riser per ogni scena
    for i, sb in enumerate(starts):
        st = sb * bar
        add(boom, st, 0.9)
        add(crash, st, 0.3, pan=-0.25)
        add(crash, st + 0.013, 0.3, pan=0.25)
        if i > 0:
            rl = 2 * beat
            tr = t_arr(rl)
            noise = rng.uniform(-1, 1, len(tr))
            seg = len(tr) // 10
            riser = np.concatenate([highpass(noise[k * seg:(k + 1) * seg], 250 + 900 * k) for k in range(10)])
            riser = np.concatenate([riser, np.zeros(len(tr) - len(riser))]) * (tr / rl) ** 2.2
            # tono che sale sotto il rumore
            riser += 0.25 * np.sin(2 * np.pi * np.cumsum(200 + 1600 * (tr / rl) ** 2) / SR) * (tr / rl) ** 2
            add(riser, st - rl, 0.2)
    end = bars * bar
    add(boom, end, 1.0)
    add(crash, end, 0.45)
    add(kick, end, 1.0)

    # --- basso wobble (Fa minore): radice per battuta
    roots = ["F", "F", "Db", "Eb", "F", "Ab", "Db", "C"]
    rates = [1, 0.5, 1 / 3, 0.5, 0.25, 1, 1 / 3, 0.25]  # periodo dell'LFO in beat, cambia ogni mezza battuta
    tt_all = np.arange(n) / SR
    freq = np.zeros(n)
    lfo = np.zeros(n)
    for b in range(bars):
        f0 = hz(roots[b % len(roots)], 1)
        i0, i1 = int(b * bar * SR), int((b + 1) * bar * SR)
        freq[i0:i1] = f0
        for h in range(2):
            j0 = int((b * bar + h * 2 * beat) * SR)
            j1 = int((b * bar + (h + 1) * 2 * beat) * SR)
            per = rates[(2 * b + h + seed) % len(rates)] * beat
            tl = (np.arange(j1 - j0) / SR)
            lfo[j0:j1] = 0.5 - 0.5 * np.cos(2 * np.pi * tl / per)
    freq[int(end * SR):] = 0
    phase = 2 * np.pi * np.cumsum(freq) / SR
    # sorgente ricca: due saw leggermente stonate + quadra
    src = np.zeros(n)
    for k in range(1, 30):
        src += np.sin(k * phase) / k * 0.6 + np.sin(k * phase * 1.007) / k * 0.4
    src += 0.5 * np.sign(np.sin(phase))
    src *= (freq > 0)
    cut = [140, 280, 560, 1100, 2200, 4200]
    layers = [lowpass(src, c) for c in cut]
    pos = lfo * (len(cut) - 1)
    wob = np.zeros(n)
    for i in range(len(cut) - 1):
        w = np.clip(1 - np.abs(pos - i), 0, 1)
        wob += layers[i] * w
    wob += layers[-1] * np.clip(pos - (len(cut) - 2), 0, 1)
    wob = np.tanh(wob * 2.2) * 0.55  # ringhio
    wob = highpass(wob, 90)
    sub = np.sin(phase) * (freq > 0) * 0.55
    # pause del basso sul rullante per far respirare il groove
    gate = np.ones(n)
    for b in range(bars):
        g0 = int((b * bar + 2 * beat) * SR)
        gate[g0:g0 + int(0.09 * SR)] = np.linspace(0.15, 1, int(0.09 * SR))
    bass = (wob + sub) * gate * sidechain
    L += bass * 0.62
    R += bass * 0.62

    # --- pad scuro molto basso (niente melodia)
    pad = np.zeros(n)
    for b in range(bars):
        tt = t_arr(bar)
        e = np.minimum(1, tt / 0.3) * np.minimum(1, (bar - tt) / 0.3)
        for nm in (roots[b % len(roots)], "Ab", "C"):
            pad_note = saw(hz(nm, 3), tt, 10) * e
            add(pad_note, b * bar, 1.0, buf=pad)
    pad = lowpass(pad, 900) * sidechain
    L += pad * 0.035
    R += np.roll(pad, int(0.013 * SR)) * 0.035

    # --- master
    fade = int(1.0 * SR)
    L[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    R[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    st = np.stack([L, R], axis=1)
    st = np.tanh(st * 1.3)
    st /= np.max(np.abs(st)) / 0.89
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--style", choices=["dubstep", "epic"], default="dubstep")
    ap.add_argument("--sections", default="2,3,3,3,2", help="battute per scena (dubstep)")
    ap.add_argument("--bars", type=int, default=10, help="battute totali (epic)")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.style == "dubstep":
        secs = [int(x) for x in a.sections.split(",")]
        a.bpm = a.bpm or 140
        st = render_dubstep(secs, a.bpm, a.seed)
        a.bars = sum(secs)
    else:
        a.bpm = a.bpm or 120
        st = render(a.bars, a.bpm, a.seed)
    pcm = (st * 32767).astype("<i2")
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"{a.out}: {len(st) / SR:.2f} s, {a.style}, {a.bpm} BPM, {a.bars} battute")


if __name__ == "__main__":
    main()
