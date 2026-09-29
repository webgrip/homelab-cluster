import html
import json
import re
from html.parser import HTMLParser

PROJECT_NAMES = {3: "Homelab Roadmap", 5: "Dark Factory", 6: "Vellum", 9: "CI/CD", 10: "Ploeg"}
SIZING_TOKEN = re.compile(
    r"\b(effort|time|unc|uncertainty|impact)\s*[/:]?\s*(S|M|L|H|hours|days|weeks|h|d|w|low|med|high)\b",
    re.IGNORECASE,
)
HEADER_BADGE = re.compile(r"^\s*<p>.*?<code>\[[^\]]*\]</code>.*?</p>", re.DOTALL)
MAX_DESCRIPTION_CHARS = 6000

AXES = {
    "effort": ("effort/", ["S", "M", "L"]),
    "time": ("time/", ["hours", "days", "weeks"]),
    "uncertainty": ("uncertainty/", ["low", "med", "high"]),
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "li", "h3", "h2", "br", "ul", "ol"):
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        joined = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def description_text(description_html):
    without_badge = HEADER_BADGE.sub("", description_html, count=1)
    extractor = _TextExtractor()
    extractor.feed(without_badge)
    text = html.unescape(extractor.text())
    text = SIZING_TOKEN.sub("", text)
    return text[:MAX_DESCRIPTION_CHARS]


def ticket_state(record):
    return json.dumps(
        {
            "title": record["title"],
            "board": PROJECT_NAMES.get(record["project_id"], str(record["project_id"])),
            "description": description_text(record["description_html"]),
        },
        ensure_ascii=False,
    )


def axis_level(labels, axis):
    prefix, levels = AXES[axis]
    found = [label[len(prefix):] for label in labels if label.startswith(prefix)]
    if len(found) != 1 or found[0] not in levels:
        return None
    return levels.index(found[0])


def theme_of(labels):
    themes = [label for label in labels if label.startswith("theme/")]
    return themes[0] if len(themes) == 1 else None


def load_jsonl(path):
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def is_epic(record):
    return record["title"].lower().startswith("epic:") or "meta" in record["labels"]
