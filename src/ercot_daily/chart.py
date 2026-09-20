"""One two-panel chart for the latest day, in a light and a dark theme."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

THEMES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#1f2328",
        "grid": "#d0d7de",
        "demand": "#8c959f",
        "net": "#cf222e",
        "dam": "#0969da",
        "rtm": "#bf8700",
    },
    "dark": {
        "bg": "#0d1117",
        "fg": "#e6edf3",
        "grid": "#30363d",
        "demand": "#8b949e",
        "net": "#ff7b72",
        "dam": "#58a6ff",
        "rtm": "#d29922",
    },
}


def draw(day_df: pd.DataFrame, summary: dict, out_dir: Path, hub: str) -> list[Path]:
    d = day_df.reset_index(drop=True)
    x = range(len(d))
    labels = [
        f"{he}{'*' if dst else ''}"
        for he, dst in zip(d["hour_ending"], d["dst"], strict=True)
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, t in THEMES.items():
        fig, (top, bottom) = plt.subplots(
            2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [3, 2]}
        )
        fig.patch.set_facecolor(t["bg"])
        top.plot(x, d["demand_mw"] / 1000, color=t["demand"], lw=2, label="Demand")
        top.plot(
            x,
            d["net_load_mw"] / 1000,
            color=t["net"],
            lw=2.5,
            label="Net load (demand − wind − solar)",
        )
        top.set_ylabel("GW")
        bottom.step(
            x, d["dam_price"], where="mid", color=t["dam"], lw=2, label="Day-ahead"
        )
        bottom.plot(
            x,
            d["rtm_price"],
            color=t["rtm"],
            lw=2,
            marker="o",
            ms=3,
            label="Real-time (hourly avg)",
        )
        bottom.set_ylabel(f"{hub} $/MWh")
        bottom.set_xticks(list(x)[::2], labels[::2])
        bottom.set_xlabel("Hour ending, Central Prevailing Time")
        for ax in (top, bottom):
            ax.set_facecolor(t["bg"])
            ax.grid(color=t["grid"], lw=0.6)
            ax.tick_params(colors=t["fg"])
            ax.yaxis.label.set_color(t["fg"])
            ax.xaxis.label.set_color(t["fg"])
            for spine in ax.spines.values():
                spine.set_color(t["grid"])
            legend = ax.legend(loc="upper left", frameon=False)
            for text in legend.get_texts():
                text.set_color(t["fg"])
        top.set_title(
            f"ERCOT — operating day {summary['day']}",
            color=t["fg"],
            loc="left",
            fontweight="bold",
        )
        fig.tight_layout()
        path = out_dir / f"latest-{name}.png"
        fig.savefig(path, dpi=130, facecolor=t["bg"])
        plt.close(fig)
        paths.append(path)
    return paths
