import json
import tempfile

import numpy as np
import unittest
import wave
from pathlib import Path

from clab.audio import AudioError, measure, render
from clab.circuit import from_dict
from clab.db import DB
from clab.solver import check, simulate

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def load(eid):
    return from_dict(json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text()), DB_)


class AudioTests(unittest.TestCase):
    def test_exp11b_oscillates_in_audio_range(self):
        circ = load("exp11b")
        res = simulate(circ)
        check(circ, res)
        self.assertTrue(res.ok)
        pid, part, f, signal = measure(circ, res)
        self.assertEqual(pid, "LS1")
        self.assertEqual(part.kind, "SPK")
        self.assertGreater(f, 400)
        self.assertLess(f, 800)
        self.assertGreater(max(signal), 1e-4)

    def test_wav_rendering(self):
        circ = load("exp11b")
        res = simulate(circ)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone.wav"
            info = render(circ, res, path=path, seconds=0.2)
            self.assertTrue(path.exists())
            self.assertGreater(info["frequency"], 400)
            with wave.open(str(path), "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getframerate(), 44100)
                self.assertAlmostEqual(w.getnframes() / 44100, 0.2, delta=0.01)
                rate = w.getframerate()
                samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
            spec = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
            freqs = np.fft.rfftfreq(len(samples), 1.0 / rate)
            fundamental = spec[(freqs > 500) & (freqs < 650)].max()
            harmonic = spec[(freqs > 1080) & (freqs < 1200)].max()
            self.assertGreater(fundamental, 0)
            self.assertGreater(harmonic, fundamental * 0.1)

    def test_exp11c_amplified(self):
        circ = load("exp11c")
        res = simulate(circ)
        check(circ, res)
        self.assertTrue(res.ok)
        pid, part, f, signal = measure(circ, res)
        self.assertEqual(pid, "LS1")
        self.assertGreater(f, 400)
        self.assertLess(f, 900)
        self.assertGreater(max(signal), 0.02)

    def test_no_transducer(self):
        circ = load("exp03")
        res = simulate(circ)
        with self.assertRaises(AudioError):
            measure(circ, res)


if __name__ == "__main__":
    unittest.main()
