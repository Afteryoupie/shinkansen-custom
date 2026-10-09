"""Left-facing watchdog vector artwork; keep geometry in sync with LLMMenuBar.swift.

Ready means a loaded model with no active requests. Only inference opens the jaw.
The native menu uses transparent template artwork; app/tray icons have a white
face for contrast on either light or dark desktops.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent
STATES = ('sleeping', 'ready', 'running', 'starting', 'offline')
LABELS = ('OFF', 'READY', 'WORKING', 'LOADING', 'OFFLINE')
# Cubic Bezier segments: start point followed by (control1, control2, end).
TOP = [(5, 21), (16, 19, 19, 18, 21, 12), (23, 3, 37, 1, 45, 5), (49, 7, 49, 10, 50, 13)]
CLOSED = [(5, 21), (3, 27, 8, 34, 15, 36), (21, 39, 27, 35, 30, 43)]
OPEN = [(5, 21), (3, 27, 9, 31, 18, 31), (17, 34, 15, 36, 12, 37), (15, 42, 23, 40, 26, 40), (29, 40, 31, 42, 32, 44)]
EAR = [(45, 6), (38, 7, 38, 14, 35, 25), (33, 34, 36, 43, 42, 44), (51, 47, 62, 38, 60, 30), (56, 23, 54, 14, 50, 9), (48, 7, 46, 6, 45, 6)]
EYE = [(22, 17), (24, 20, 27, 20, 29, 19)]


def points(path):
    result = [path[0]]
    for x1, y1, x2, y2, x3, y3 in path[1:]:
        x0, y0 = result[-1]
        for step in range(1, 41):
            t = step / 40
            u = 1 - t
            result.append((u**3*x0 + 3*u*u*t*x1 + 3*u*t*t*x2 + t**3*x3,
                           u**3*y0 + 3*u*u*t*y1 + 3*u*t*t*y2 + t**3*y3))
    return result


def svg_path(path):
    return 'M' + ' '.join(map(str, path[0])) + ''.join(' C' + ' '.join(map(str, p)) for p in path[1:])


def svg_markup(status):
    jaw = OPEN if status == 'running' else CLOSED
    eye = ('<ellipse cx="26.5" cy="18" rx="3.5" ry="4"/>' if status in ('ready', 'running', 'starting')
           else f'<path d="{svg_path(EYE)}" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>')
    return (f'<g fill="currentColor"><g fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{svg_path(TOP)}"/><path d="{svg_path(jaw)}"/></g>'
            f'<path d="{svg_path(EAR)}Z"/><ellipse cx="6.5" cy="23" rx="3.5" ry="3"/>{eye}</g>')


def draw_icon(status, size=64):
    scale = 16
    image = Image.new('RGBA', (64 * scale, 64 * scale))
    draw = ImageDraw.Draw(image)
    ink = '#171717'
    def xy(p):
        return (round(p[0]*scale), round((p[1]+8)*scale))
    def curve(path):
        pts = [xy(p) for p in points(path)]
        draw.line(pts, fill=ink, width=round(2.6*scale), joint='curve')
        for x, y in (pts[0], pts[-1]):
            r = 1.3 * scale
            draw.ellipse((x-r, y-r, x+r, y+r), fill=ink)
    def ellipse(box, fill=ink):
        x1, y1 = xy(box[:2]); x2, y2 = xy(box[2:])
        draw.ellipse((x1, y1, x2, y2), fill=fill)
    jaw = OPEN if status == 'running' else CLOSED
    # Neutral white underlay, including a thin ear rim, keeps dark trays legible.
    silhouette = points(TOP) + points(EAR)[1:] + list(reversed(points(jaw)))
    outline = [xy(p) for p in silhouette]
    draw.polygon(outline, fill='white')
    ear = [xy(p) for p in points(EAR)]
    draw.line(ear, fill='white', width=2*scale, joint='curve')
    curve(TOP); curve(jaw)
    draw.polygon(ear, fill=ink)
    ellipse((3, 20, 10, 26))
    if status in ('ready', 'running', 'starting'):
        ellipse((23, 14, 30, 22))
        ellipse((24.5, 15, 26.5, 17), 'white')
    else:
        curve(EYE)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    for state in STATES:
        draw_icon(state, 1024).save(ASSETS / f'watchdog-{state}.png')
        draw_icon(state, 256).save(ASSETS / f'watchdog-{state}.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(256,256)])
        (ASSETS / f'watchdog-{state}.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 48">' + svg_markup(state) + '</svg>\n')
    draw_icon('ready', 1024).save(ASSETS / 'guardian-1024.png')
    draw_icon('ready', 1024).save(ASSETS / 'guardian.icns')
    preview = Image.new('RGB', (960, 360), '#F5F3EC')
    pen = ImageDraw.Draw(preview)
    font = ImageFont.load_default(size=18)
    for index, state in enumerate(STATES):
        x = index * 192
        icon = draw_icon(state, 152)
        preview.paste(icon, (x+20, 12), icon)
        pen.text((x+24, 185), LABELS[index], font=font, fill='#242620')
        for size, offset in [(16, 24), (24, 74), (32, 126)]:
            icon = draw_icon(state, size)
            preview.paste(icon, (x+offset, 231), icon)
            pen.text((x+offset, 274), str(size), font=font, fill='#647084')
        pen.rectangle((x, 306, x+191, 359), fill='#242620')
        icon = draw_icon(state, 32)
        preview.paste(icon, (x+80, 316), icon)
    preview.save(ASSETS / 'watchdog-states-preview.png')


if __name__ == '__main__':
    main()
