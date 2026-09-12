from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

COLORS = {
    "direct": "#2563eb",
    "transitive": "#93c5fd",
    "peers": "#9333ea",
    "major": "#7c3aed",
    "minor": "#a78bfa",
    "patch": "#ddd6fe",
    "critical": "#991b1b",
    "high": "#dc2626",
    "medium": "#f59e0b",
    "low": "#22c55e",
}


def write_ring_thumbnail(
    path: Path, metrics: dict[str, dict[str, int]], *, size: int = 160
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    rings = (
        ("vulnerabilities", (4, 4, size - 4, size - 4), 16),
        ("updates", (25, 25, size - 25, size - 25), 16),
        ("scope", (46, 46, size - 46, size - 46), 16),
    )
    for dimension, bounds, width in rings:
        values = metrics.get(dimension, {})
        total = sum(max(0, value) for value in values.values())
        start = -90.0
        if total == 0:
            draw.arc(bounds, 0, 360, fill="#d1d5db", width=width)
            continue
        for category, value in values.items():
            end = start + (360.0 * max(0, value) / total)
            draw.arc(
                bounds, start, end, fill=COLORS.get(category, "#64748b"), width=width
            )
            start = end
    image.save(path)
