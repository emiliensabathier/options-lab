"""Render the README's smile chart from the latest frozen capture.

    python scripts/build_readme_chart.py
"""

from __future__ import annotations

from pathlib import Path

from olab.__main__ import latest_chain
from olab.pipeline import run_surface
from olab.report.charts import smile_figure

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "smile.png"


def main() -> None:
    chain = latest_chain(ROOT / "data" / "raw")
    surface = run_surface(chain, chain.with_suffix(".json"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    smile_figure(surface.quotes.table, surface.surfaces).savefig(
        OUTPUT, dpi=150, bbox_inches="tight", metadata={"Software": None}
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
