#!/usr/bin/env python3
"""Split the ALREADY APPROVED exact source/logo layers into 3 arcs.

Each existing nontransparent pixel is copied unchanged to exactly one layer.
No tracing, invented vectors, recolouring, or new graphics.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'public/assets/loading/logo-pieces/arcoiris.png'
OUT = ROOT / 'public/assets/loading/logo-pieces'


def is_red(p):
    r, g, b, a = p
    return a > 30 and r > 115 and r > g * 1.52 and r > b * 1.37


def split():
    src = Image.open(SOURCE).convert('RGBA')
    w, h = src.size
    reds = {}
    for x in range(w):
        ys = [y for y in range(42, min(h, 140)) if is_red(src.getpixel((x, y)))]
        if ys:
            reds[x] = (min(ys), max(ys))
    assert len(reds) >= 60, 'No se ha encontrado la franja roja original'
    xs = sorted(reds)
    names = ['arco-exterior', 'arco-rojo', 'arco-interior']
    layers = {name: Image.new('RGBA', src.size) for name in names}
    for y in range(h):
        for x in range(w):
            rgba = src.getpixel((x,y))
            if not rgba[3]:
                continue
            nearest = min(xs, key=lambda k: abs(k - x))
            ymin, ymax = reds[nearest]
            if is_red(rgba):
                name = 'arco-rojo'
            elif y < ymin:
                name = 'arco-exterior'
            elif y > ymax:
                name = 'arco-interior'
            else:
                # At antialiased boundaries, keep red edge pixels with its stripe,
                # and existing dark navy pixels on the inner strip.
                r, g, b, _ = rgba
                if b > r * 1.23 and b > g * 1.12:
                    name = 'arco-interior' if y > (ymin + ymax) / 2 else 'arco-exterior'
                else:
                    name = 'arco-rojo'
            layers[name].putpixel((x,y),rgba)
    for y in range(h):
        for x in range(w):
            rgba=src.getpixel((x,y))
            found=[k for k in names if layers[k].getpixel((x,y))[3]]
            assert (len(found)==1 and layers[found[0]].getpixel((x,y))==rgba) if rgba[3] else not found
    for name in names:
        layers[name].save(OUT / f'{name}.png', optimize=True)
        assert layers[name].getbbox(), f'Capa vacia: {name}'
    print('OK: 3 franjas, cada pixel original preservado, sin inventar figuras.')

if __name__ == '__main__':
    split()
