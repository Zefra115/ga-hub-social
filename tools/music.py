#!/usr/bin/env python3
"""Base musicale originale per i reel GA.Hub, sintetizzata da zero (nessun campione, nessuna licenza).

  python3 -I tools/music.py --out assets/music/reel-base.wav [--bars 10] [--bpm 120] [--seed 1]

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


NOTE = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--bars", type=int, default=10)
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    st = render(a.bars, a.bpm, a.seed)
    pcm = (st * 32767).astype("<i2")
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"{a.out}: {len(st) / SR:.2f} s, {a.bpm} BPM, {a.bars} battute")


if __name__ == "__main__":
    main()
