#!/usr/bin/env python3
"""Recreate the seven exact layers of the approved Sunset Beach Club PNG.

Usage: python tools/sbc_logo_split.py
Requires Pillow. Never invents vector geometry or changes the logo artwork.
Only run against the original 342x291 PNG shipped in this frontend.
"""
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / 'public/assets/loading/sunset-beach-club-logo.png'
DEST = BASE / 'public/assets/loading/logo-pieces'
NAMES = ('sol', 'arcoiris', 'estrella-1', 'estrella-2', 'estrella-3', 'estrella-4', 'nombre')


def main():
    source = Image.open(SOURCE).convert('RGBA')
    if source.size != (342, 291):
        raise ValueError('Se requiere el logo original SBC aprobado de 342x291')
    width, height = source.size
    layers = {name: Image.new('RGBA', source.size) for name in NAMES}
    for y in range(height):
        for x in range(width):
            rgba = source.getpixel((x, y))
            if not rgba[3]:
                continue
            if y < 43:
                name = ('estrella-1' if x < 132 else 'estrella-2'
                        if x < 170 else 'estrella-3' if x < 208 else 'estrella-4')
            elif y < 125 or (y < 140 and 134 <= x <= 205):
                r, g, b, _ = rgba
                is_sun = 133 <= x <= 205 and (
                    (y >= 80 and r > 175 and g > 135 and b < 115) or
                    (y >= 110 and r > 110 and r > g * 1.65 and r > b * 1.2))
                name = 'sol' if is_sun else 'arcoiris'
            else:
                name = 'nombre'
            layers[name].putpixel((x, y), rgba)
    # Every visible source pixel is preserved exactly in one and only one layer.
    for y in range(height):
        for x in range(width):
            pixel = source.getpixel((x, y))
            hits = [name for name, layer in layers.items() if layer.getpixel((x, y))[3]]
            if pixel[3]:
                assert len(hits) == 1 and layers[hits[0]].getpixel((x, y)) == pixel
            else:
                assert not hits
    DEST.mkdir(parents=True, exist_ok=True)
    for name, layer in layers.items():
        layer.save(DEST / (name + '.png'), optimize=True)
    print('OK: 7 capas, 4 estrellas, sin perder ni anadir pixeles visibles')


if __name__ == '__main__':
    main()
