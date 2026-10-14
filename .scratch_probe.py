import os, tempfile
from mutagen.mp3 import MP3
from mutagen.id3 import APIC, RVRB, TIT2, TPE1, TALB, TXXX, ID3, ID3NoHeaderError

def mpeg_frame():
    return bytes([0xFF, 0xFB, 0x90, 0xC0]) + b"\x00" * 413

def build_mp3(path, frames=8):
    with open(path, "wb") as f:
        for _ in range(frames):
            f.write(mpeg_frame())

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "song.mp3")
build_mp3(p)

# Approach A: build ID3 object directly and attach
audio = MP3(p)
tags = audio.tags if isinstance(audio.tags, ID3) else None
print("has tags initially:", bool(tags))
id3obj = ID3()
if tags is not None:
    id3obj = tags
id3obj.add(TPE1(encoding=3, text="Aerosmith"))
id3obj.add(TIT2(encoding=3, text="Dream On - Lyrics (Official HD Video)"))
id3obj.add(TALB(encoding=3, text="Toys in the Attic"))
id3obj.add(RVRB())
id3obj.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", value="-8.2 dB"))
print("TXXX created:", repr(id3obj.getall("TXXX:desc=REPLAYGAIN_TRACK_GAIN")))

audio.tags = id3obj
audio.save()
r1 = open(p, "rb").read()

a2 = MP3(p)
keys = sorted(k for k in a2.tags.keys())
print("frames after save+reload:", keys)
txxx = a2.tags.getall("TXXX:desc=REPLAYGAIN_TRACK_GAIN")
print("TXXX after reload:", txxx)
# mutate something else and re-save, check TXXX still there
a2.tags["TIT2"] = TIT2(encoding=3, text="Dream On")
a2.save()
r2 = open(p, "rb").read()

def audio_part(r):
    i = r.find(b"\xff\xfb", 10)
    return r[i:] if i >= 0 else r

print("audio preserved:", audio_part(r1) == audio_part(r2))
a3 = MP3(p)
txxx3 = a3.tags.getall("TXXX:desc=REPLAYGAIN_TRACK_GAIN")
print("TXXX after second save:", txxx3)
rv3 = a3.tags.getall("RVRB")
print("RVRB after second save:", len(rv3))
