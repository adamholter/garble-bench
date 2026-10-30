"""Build GarbleBench prompts: each base question corrupted at increasing rates.

Corruption is nested: every character gets one fixed random draw, and a character is corrupted
once the level's rate passes its draw. So level N+1 keeps every error from level N and adds more.
"""
import json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATES = [0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0]

QUESTIONS = [
    ("capital", "What is the capital city of Australia?", "Canberra"),
    ("austen", "Who wrote the novel Pride and Prejudice?", "Jane Austen"),
    ("gold", "What is the chemical symbol for gold on the periodic table?", "Au"),
    ("hexagon", "How many sides does a hexagon have?", "6"),
    ("mars", "Which planet in our solar system is known as the Red Planet?", "Mars"),
    ("ocean", "What is the largest ocean on Earth?", "Pacific Ocean"),
    ("mona", "Who painted the Mona Lisa?", "Leonardo da Vinci"),
    ("titanic", "In what year did the Titanic sink?", "1912"),
    ("sqrt", "What is the square root of 144?", "12"),
    ("photo", "What gas do plants absorb from the air to carry out photosynthesis?", "carbon dioxide (CO2)"),
    ("everest", "What is the tallest mountain in the world above sea level?", "Mount Everest"),
    ("minutes", "How many minutes are there in one full day?", "1440"),
    ("freeze", "What is the freezing point of water in degrees Fahrenheit?", "32"),
    ("moon", "Who was the first person to walk on the moon?", "Neil Armstrong"),
    ("amazon", "What is the longest river in South America?", "Amazon River"),
    ("piano", "How many keys are on a standard piano?", "88"),
    ("yen", "What is the name of the currency used in Japan?", "yen"),
    ("heart", "Which organ in the human body pumps blood through the veins and arteries?", "heart"),
    ("brazil", "What is the main language spoken in Brazil?", "Portuguese"),
    ("apples", "If I have three apples, buy five more, and then eat two, how many apples do I have left?", "6"),
    ("spider", "How many legs does a spider have?", "8"),
    ("romeo", "Which playwright wrote Romeo and Juliet?", "William Shakespeare"),
    ("speed", "Roughly how fast does light travel in a vacuum, in kilometers per second?", "about 300,000 km/s (299,792)"),
    ("ww2", "In what year did World War II end?", "1945"),
]

ROWS = ["1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"]
POS = {c: (r, i) for r, row in enumerate(ROWS) for i, c in enumerate(row)}
STRAY = "abcdefghijklmnopqrstuvwxyz;',./[]\\`~-=0123456789"
PUNCT = set("?,.'!;:")


def neighbor(c, rng):
    lo = c.lower()
    if lo not in POS:
        return rng.choice("abcdefghijklmnopqrstuvwxyz")
    r, i = POS[lo]
    opts = [ROWS[rr][ii] for rr in (r - 1, r, r + 1) for ii in (i - 1, i, i + 1)
            if 0 <= rr < 4 and 0 <= ii < len(ROWS[rr]) and (rr, ii) != (r, i)]
    out = rng.choice(opts)
    return out.upper() if c.isupper() else out


def plan(text, seed):
    rng = random.Random(seed)
    p = []
    for c in text:
        p.append({
            "u": rng.random(),        # main corruption draw
            "uc": rng.random(),       # capitalization draw
            "op": rng.choices(["typo", "drop", "stray", "swap"], [0.36, 0.26, 0.22, 0.16])[0],
            "nb": neighbor(c, rng),
            "st": rng.choice(STRAY),
        })
    return p


def corrupt(text, p, rate):
    out, i = [], 0
    while i < len(text):
        c, d = text[i], p[i]
        if c.isupper() and d["uc"] < min(1, rate * 2):
            c = c.lower()
        if c in PUNCT:
            if d["u"] >= min(1, rate * 2.5):
                out.append(c)
            i += 1
            continue
        if d["u"] >= rate:
            out.append(c)
            i += 1
            continue
        op = d["op"]
        if c == " " and op in ("typo", "swap"):
            op = "drop"  # words run together
        if op == "typo":
            out.append(d["nb"])
        elif op == "stray":
            out.append(c + d["st"])
        elif op == "swap" and i + 1 < len(text) and text[i + 1] not in PUNCT:
            out.append(text[i + 1] + c)
            i += 1
        elif op == "swap":
            out.append(c)
        # drop: nothing
        i += 1
    return "".join(out)


def main():
    items = []
    for qi, (qid, q, ans) in enumerate(QUESTIONS):
        p = plan(q, 1000 + qi)
        for li, rate in enumerate(RATES):
            items.append({"id": f"{qid}-L{li:02d}", "qid": qid, "level": li, "rate": rate,
                          "question": q, "answer": ans, "prompt": corrupt(q, p, rate)})
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/items.json").write_text(json.dumps({"rates": RATES, "items": items}, indent=1))
    print(len(items), "items")


if __name__ == "__main__":
    main()
