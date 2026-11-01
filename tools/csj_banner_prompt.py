"""CS Junkie banner prompt builder (master skill v39 section 5). One text-free 20-layer prompt per clip.

Usage:
  python3 csj_banner_prompt.py <inputs.json> <out_dir> [--theme NAME]

Picks a theme at random from tools/banner_themes.json (the approved bank of 20), unless --theme is given.
Writes <clip>_banner_prompt.md with the theme, the colours from inputs, and the 20 layer slots.
The banner text is the top title, added later as text, so the prompt itself has no text.
Art direction per theme comes from tools/banner_art_direction.json (rewritten 29 Oct).
The 20 layers are grouped: 1 to 8 back, 9 to 14 middle, 15 to 20 front.
The theme name appears only in the header, never in the prompt text.
The chosen theme name is written back into the inputs file as "theme" (Jord reads it there).
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANK = HERE / "banner_themes.json"


def hex_or_none(v):
    return v if v else None


ART = json.loads((HERE / "banner_art_direction.json").read_text())["themes"]


def build(inputs, theme):
    a = ART[theme]
    # Jord, 30 Oct: the banner takes no nationality colours. Colours are fixed per banner in its batch.
    title = inputs.get("top_title", "").upper()
    lines = [
        f"# Banner prompt: {inputs.get('player_name', '?')}",
        "",
        f"Theme (header only, not in the prompt): {theme}",
        "Palette: none. Banner colours are fixed in the banner batch, not set by the clip.",
        "Export 1100x600, soft edges on all four sides, no border.",
        "",
        "Prompt (animated cartoon style, bold ink outlines, extremely detailed):",
        "A wide cartoon banner, 1100x600. No text, no letters, no logos, no border.",
        f"Scene: {a['scene']}",
        f"Composition: {a['composition']} Keep the main subject inside the outer 140 px, since the edges fade out.",
        f"Layers 1 to 8, back: {a['back']}",
        f"Layers 9 to 14, middle: {a['middle']}",
        f"Layers 15 to 20, front: {a['front']}",
        f"Mood: {a['mood']}",
        "",
        f"Top title (added later as text, not in the image): {title}",
    ]
    return "\n".join(lines) + "\n"


def main(inputs_path, out_dir, theme=None):
    inputs = json.loads(Path(inputs_path).read_text())
    bank = json.loads(BANK.read_text())["themes"]
    if theme is None:
        theme = random.choice(bank)
    if theme not in bank:
        raise SystemExit(f"theme {theme!r} is not in the bank")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{inputs['clip_id']}_banner_prompt.md"
    p.write_text(build(inputs, theme))
    inputs["theme"] = theme
    Path(inputs_path).write_text(json.dumps(inputs, indent=2))
    print(json.dumps({"clip_id": inputs["clip_id"], "theme": theme, "prompt": str(p),
                      "status": "art direction written per theme; layers grouped back, middle, front"}, indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]
    theme = None
    if "--theme" in args:
        i = args.index("--theme")
        theme = args[i + 1]
        del args[i:i + 2]
    main(args[0], args[1], theme)
