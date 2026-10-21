import math
import shutil
import subprocess
import tempfile
import wave

import numpy as np

PLAYERS = (
    ("paplay", []),
    ("pw-play", []),
    ("aplay", ["-q"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
)


class AudioError(Exception):
    pass


def transducer(circ):
    for pid, p in circ.parts.items():
        if p.kind in ("SPK", "BUZZ"):
            return pid, p
    return None, None


def frequency(t, y):
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)
    if len(y) < 3:
        return None
    lo, hi = float(np.min(y)), float(np.max(y))
    if hi - lo < 1e-9:
        return None
    threshold = lo + (hi - lo) * 0.5
    rising = np.where((y[:-1] <= threshold) & (y[1:] > threshold))[0]
    if len(rising) < 2:
        return None
    periods = np.diff(t[rising])
    periods = periods[periods > 0]
    if len(periods) == 0:
        return None
    return float(1.0 / np.median(periods))


def measure(circ, res):
    pid, part = transducer(circ)
    if part is None:
        raise AudioError("nessun altoparlante o buzzer nel circuito")
    if res is None or res.time is None:
        raise AudioError("serve una simulazione transitoria")
    key = f"I({pid})"
    if key in res.waves:
        signal = res.waves[key]
    else:
        net = circ.net_of(pid, part.spec.pins[0])
        signal = res.waves.get(f"V({net})")
    if signal is None:
        raise AudioError(f"segnale {key} non disponibile")
    f = frequency(res.time, signal)
    if f is None:
        raise AudioError("oscillazione non rilevata")
    return pid, part, float(f), signal


def _write_wav(path, samples, rate):
    data = np.clip(samples, -1.0, 1.0)
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def play(path):
    for name, args in PLAYERS:
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe, *args, str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return name
    return None


def render(circ, res, path=None, seconds=0.6, rate=44100, play_audio=False):
    pid, part, f, signal = measure(circ, res)
    if not 20.0 <= f <= 20000.0:
        raise AudioError(f"frequenza {f:.0f} Hz fuori dall'udibile")
    if path is None:
        handle = tempfile.NamedTemporaryFile(prefix="elettrolab-", suffix=".wav", delete=False)
        path = handle.name
        handle.close()
    n = max(1, int(seconds * rate))
    t = np.arange(n, dtype=float) / rate
    tone = np.sign(np.sin(2.0 * math.pi * f * t))
    k = max(1, int(rate / 12000))
    tone = np.convolve(tone, np.ones(k) / k, mode="same")
    fade = min(n // 4, int(0.01 * rate))
    if fade > 0:
        env = np.ones(n)
        env[:fade] = np.linspace(0.0, 1.0, fade)
        env[-fade:] = np.linspace(1.0, 0.0, fade)
        tone *= env
    tone *= 0.35
    _write_wav(path, tone, rate)
    player = play(path) if play_audio else None
    return {
        "path": str(path),
        "frequency": f,
        "duration": seconds,
        "rate": rate,
        "player": player,
        "transducer": pid,
    }
