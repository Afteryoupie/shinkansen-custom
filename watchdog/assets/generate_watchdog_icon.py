"""Draw the LLM watchdog identity and state icons from simple vector geometry."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent
COLORS = {'running': '#16834A', 'sleeping': '#647084', 'starting': '#C47A05', 'offline': '#9B3C43'}
LABELS = {'running': 'RUNNING / ON', 'sleeping': 'SLEEPING / OFF', 'starting': 'LOADING', 'offline': 'DISCONNECTED'}


def draw_icon(status, size=64):
    # Supersampling preserves strong shapes at 16 px without tiny typography.
    scale = 16
    image = Image.new('RGBA', (64 * scale, 64 * scale))
    draw = ImageDraw.Draw(image)
    def box(coords):
        return tuple(round(value * scale) for value in coords)
    def polygon(points, fill):
        draw.polygon([(round(x * scale), round(y * scale)) for x, y in points], fill=fill)
    def line(points, fill, width=3):
        draw.line([(round(x * scale), round(y * scale)) for x, y in points], fill=fill, width=width * scale)
    color = COLORS.get(status, COLORS['offline'])
    white, ink = '#FFFFFF', '#17303B'
    draw.rounded_rectangle(box((2, 2, 62, 62)), radius=14 * scale, fill=color)
    # A watchful robot dog: upright ears, broad muzzle and chip-like nose.
    polygon([(10, 28), (10, 10), (26, 19)], white)
    polygon([(38, 19), (54, 10), (54, 28)], white)
    draw.rounded_rectangle(box((12, 18, 52, 49)), radius=11 * scale, fill=white)
    if status == 'sleeping':
        line([(19, 29), (27, 29)], ink)
        line([(37, 29), (45, 29)], ink)
    else:
        draw.rounded_rectangle(box((20, 25, 26, 32)), radius=2 * scale, fill=ink)
        draw.rounded_rectangle(box((38, 25, 44, 32)), radius=2 * scale, fill=ink)
    draw.rounded_rectangle(box((27, 35, 37, 41)), radius=2 * scale, fill=ink)
    line([(32, 39), (32, 45)], ink, 2)
    # Large high-contrast state badge, legible independently of its color.
    draw.ellipse(box((39, 39, 64, 64)), fill=ink, outline=white, width=2 * scale)
    if status == 'running':
        polygon([(48, 45), (48, 58), (58, 51.5)], '#61F19D')
    elif status == 'sleeping':
        draw.rectangle(box((46, 45, 50, 58)), fill=white)
        draw.rectangle(box((54, 45, 58, 58)), fill=white)
    elif status == 'starting':
        polygon([(46, 45), (58, 45), (52, 51), (58, 58), (46, 58), (52, 51)], '#FFD86B')
    else:
        line([(47, 46), (57, 57)], white, 3)
        line([(57, 46), (47, 57)], white, 3)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    for status in COLORS:
        draw_icon(status, 1024).save(ASSETS / f'watchdog-{status}.png')
        draw_icon(status, 256).save(ASSETS / f'watchdog-{status}.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(256,256)])
    # The app identity is the watchful, ready dog. Runtime icons use each state.
    draw_icon('running', 1024).save(ASSETS / 'guardian-1024.png')
    draw_icon('running', 1024).save(ASSETS / 'guardian.icns')
    preview = Image.new('RGB', (960, 340), '#F5F3EC')
    pen = ImageDraw.Draw(preview)
    try:
        font = ImageFont.truetype('segoeuib.ttf', 17)
    except OSError:
        font = ImageFont.load_default(size=17)
    for index, status in enumerate(COLORS):
        x = index * 240
        preview.paste(draw_icon(status, 144), (x + 48, 34), draw_icon(status, 144))
        pen.text((x + 24, 200), LABELS[status], font=font, fill='#242620')
        for size, offset in [(16, 40), (24, 94), (32, 151)]:
            icon = draw_icon(status, size)
            preview.paste(icon, (x + offset, 248), icon)
            pen.text((x + offset, 294), str(size), font=font, fill='#647084')
    preview.save(ASSETS / 'watchdog-states-preview.png')


if __name__ == '__main__':
    main()
