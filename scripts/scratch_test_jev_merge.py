import sys
sys.path.append('c:/LLM_Project/translation_tools/shinkansen-custom/scripts')
from yt_subtitle_pipeline_loop import JevClient

jev = JevClient()

pairs = [
    ("it is almost the exact same car, but when", "you drive it on the track it feels different"),
    ("Some very exciting news from Nissan. We", "are getting a new Skyline."),
    ("It is going to be a sedan, probably rear-wheel drive", "architecture, and potentially with a six-speed manual"),
    ("This car is very fast.", "The interior is also very luxurious.")
]

for a, b in pairs:
    q = "Does segment A end with an incomplete thought, hanging conjunction, or split sentence that should be merged with segment B?"
    res = jev.boolean(state=f"Segment A: {a}\nSegment B: {b}", question=q)
    print(f"A: {a}")
    print(f"B: {b}")
    print(f"==> Jev Decision: {res['decision']}, Confidence: {res.get('confidence')}, Source: {res.get('source')}\n")
