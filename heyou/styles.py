"""Shared randomization pools — variety per generation while identity stays locked.

(Cute You 2 has a fixed style and transfers the real clothing from the photo, so it only
consumes the seed; the prompt is logged and used by workflows that expose a prompt node.)
"""
from __future__ import annotations

import random

OUTFITS = ["casual hoodie", "leather jacket", "denim jacket", "elegant dress",
           "varsity jacket", "trench coat", "knit sweater", "bomber jacket"]
BACKGROUNDS = ["neon city night", "cozy cafe", "starry sky", "graffiti wall",
               "tropical beach", "rooftop bar", "autumn park", "abstract gradient"]
ACCESSORIES = ["sunglasses", "headphones", "a beanie", "a scarf", "a cap", "none"]
EXPRESSIONS = ["smiling", "laughing", "confident", "playful wink", "calm"]


def random_style(rng: random.Random) -> dict:
    return {
        "outfit": rng.choice(OUTFITS),
        "background": rng.choice(BACKGROUNDS),
        "accessory": rng.choice(ACCESSORIES),
        "expression": rng.choice(EXPRESSIONS),
    }


def build_prompt(style: dict) -> str:
    acc = "" if style["accessory"] == "none" else f", wearing {style['accessory']}"
    return (f"2D cartoon portrait, {style['expression']}, wearing {style['outfit']}{acc}, "
            f"{style['background']} background, clean lines, vibrant colors")
