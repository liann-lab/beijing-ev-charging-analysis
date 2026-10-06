"""Create the first set of exploratory charts from the public Parquet files."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
FIGURE_DIR = PROJECT_ROOT / "reports" / "figures"

ORDER_FILES = {
    "2025-01": RAW_DIR / "orders_2025-01_public.parquet",
    "2025-07": RAW_DIR / "orders_2025-07_public.parquet",
}
STATION_FILE = RAW_DIR / "stations_monthly_public.parquet"

MONTH_LABELS = {"2025-01": "Jan 2025", "2025-07": "Jul 2025"}
MONTH_COLORS = {"2025-01": "#4472C4", "2025-07": "#ED7D31"}
SITE_NAME_MAP = {
    "其他": "Other",
    "公共机构": "Public institutions",
    "企事业单位": "Enterprises",
    "居民区": "Residential areas",
    "居住区": "Residential areas",
    "大型建筑配建停车场": "Large-building parking",
    "写字楼": "Office buildings",
    "工业园区": "Industrial parks",
    "大型文体设施": "Cultural and sports venues",
    "交通枢纽": "Transport hubs",
    "城际高速服务区": "Highway service areas",
    "路边停车位": "Curbside parking",
    "城市绿地": "Urban green spaces",
    "风景区": "Scenic areas",
    "出租车": "Taxi",
    "公交场站": "Bus depots",
    "加油加气站": "Fuel stations",
}


def set_chart_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 180,
            "font.size": 10,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.7,
        }
    )


def normalize_site(value: object) -> str:
    text = str(value)
    return SITE_NAME_MAP.get(text, text)


def collect_order_summaries() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    monthly_rows: list[dict[str, float | str]] = []
    hourly_rows: list[dict[str, float | int | str]] = []
    site_rows: list[dict[str, float | str]] = []
    energy_samples: list[pd.DataFrame] = []

    for month, path in ORDER_FILES.items():
        parquet_file = pq.ParquetFile(path)
        hourly_energy = np.zeros(24, dtype=float)
        hourly_sessions = np.zeros(24, dtype=np.int64)
        site_counts: Counter[str] = Counter()
        total_energy = 0.0
        sampled_parts: list[np.ndarray] = []
        random = np.random.default_rng(202501 if month == "2025-01" else 202507)

        for batch in parquet_file.iter_batches(
            batch_size=250_000,
            columns=["charge_start_time", "total_elec_kwh", "construction_site"],
        ):
            data = batch.to_pandas()
            energy = data["total_elec_kwh"].to_numpy(dtype=float, copy=False)
            hours = data["charge_start_time"].dt.hour.to_numpy()
            valid = np.isfinite(energy)

            total_energy += float(np.nansum(energy))
            hourly_energy += np.bincount(hours[valid], weights=energy[valid], minlength=24)
            hourly_sessions += np.bincount(hours[valid], minlength=24)
            site_counts.update(normalize_site(value) for value in data["construction_site"])

            valid_energy = energy[valid & (energy >= 0)]
            sample_size = min(2_500, len(valid_energy))
            if sample_size:
                sample_index = random.choice(len(valid_energy), size=sample_size, replace=False)
                sampled_parts.append(valid_energy[sample_index])

        row_count = parquet_file.metadata.num_rows
        monthly_rows.append(
            {
                "month": month,
                "sessions": row_count,
                "energy_kwh": total_energy,
                "average_energy_kwh": total_energy / row_count,
            }
        )
        for hour in range(24):
            hourly_rows.append(
                {
                    "month": month,
                    "hour": hour,
                    "energy_kwh": hourly_energy[hour],
                    "sessions": int(hourly_sessions[hour]),
                }
            )
        for site, count in site_counts.items():
            site_rows.append({"month": month, "site": site, "sessions": count})

        energy_samples.append(
            pd.DataFrame(
                {
                    "month": month,
                    "energy_kwh": np.concatenate(sampled_parts),
                }
            )
        )

    return (
        pd.DataFrame(monthly_rows),
        pd.DataFrame(hourly_rows),
        pd.DataFrame(site_rows),
        pd.concat(energy_samples, ignore_index=True),
    )


def add_bar_labels(axis: plt.Axes, labels: list[str]) -> None:
    for bar, label in zip(axis.patches, labels, strict=True):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            label,
            ha="center",
            va="bottom",
            fontsize=9,
        )


def plot_monthly_overview(monthly: pd.DataFrame) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    colors = [MONTH_COLORS[month] for month in monthly["month"]]
    labels = [MONTH_LABELS[month] for month in monthly["month"]]

    axes[0].bar(labels, monthly["sessions"] / 1_000_000, color=colors, width=0.58)
    axes[0].set_title("Charging sessions")
    axes[0].set_ylabel("Sessions (million)")
    add_bar_labels(axes[0], [f"{value / 1_000_000:.2f}M" for value in monthly["sessions"]])

    axes[1].bar(labels, monthly["energy_kwh"] / 1_000_000, color=colors, width=0.58)
    axes[1].set_title("Delivered energy")
    axes[1].set_ylabel("Energy (GWh)")
    add_bar_labels(axes[1], [f"{value / 1_000_000:.1f}" for value in monthly["energy_kwh"]])

    figure.suptitle("Monthly public EV charging activity in Beijing", fontsize=15)
    figure.tight_layout()
    figure.savefig(FIGURE_DIR / "01-monthly-overview.png", bbox_inches="tight")
    plt.close(figure)


def plot_hourly_profile(hourly: pd.DataFrame) -> None:
    figure, axis = plt.subplots(figsize=(10, 5))
    for month in ORDER_FILES:
        subset = hourly[hourly["month"] == month].sort_values("hour")
        average_daily_mwh = subset["energy_kwh"] / 31 / 1_000
        axis.plot(
            subset["hour"],
            average_daily_mwh,
            color=MONTH_COLORS[month],
            marker="o",
            markersize=3.5,
            linewidth=2,
            label=MONTH_LABELS[month],
        )

    axis.set_title("Average daily charging energy by session start hour")
    axis.set_xlabel("Session start hour")
    axis.set_ylabel("Average daily energy (MWh)")
    axis.set_xticks(range(0, 24, 2))
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(FIGURE_DIR / "02-hourly-energy-profile.png", bbox_inches="tight")
    plt.close(figure)


def plot_site_mix(site_summary: pd.DataFrame) -> None:
    totals = site_summary.groupby("month")["sessions"].sum()
    site_summary = site_summary.copy()
    site_summary["share"] = site_summary.apply(
        lambda row: row["sessions"] / totals[row["month"]] * 100,
        axis=1,
    )
    top_sites = (
        site_summary.groupby("site")["sessions"].sum().nlargest(10).index.tolist()
    )
    pivot = (
        site_summary[site_summary["site"].isin(top_sites)]
        .pivot(index="site", columns="month", values="share")
        .fillna(0)
        .reindex(top_sites[::-1])
    )

    figure, axis = plt.subplots(figsize=(10, 6))
    y = np.arange(len(pivot.index))
    width = 0.36
    for offset, month in zip((-width / 2, width / 2), ORDER_FILES, strict=True):
        axis.barh(
            y + offset,
            pivot[month],
            height=width,
            color=MONTH_COLORS[month],
            label=MONTH_LABELS[month],
        )
    axis.set_yticks(y, pivot.index)
    axis.set_xlabel("Share of monthly sessions (%)")
    axis.set_title("Charging-session mix by site category")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(FIGURE_DIR / "03-site-session-share.png", bbox_inches="tight")
    plt.close(figure)


def plot_energy_distribution(samples: pd.DataFrame) -> None:
    figure, axis = plt.subplots(figsize=(10, 5))
    for month in ORDER_FILES:
        values = samples.loc[
            (samples["month"] == month) & (samples["energy_kwh"] > 0),
            "energy_kwh",
        ].sort_values()
        x = values.to_numpy()
        y = np.arange(1, len(x) + 1) / len(x) * 100
        axis.plot(x, y, color=MONTH_COLORS[month], linewidth=2, label=MONTH_LABELS[month])

    axis.set_xscale("log")
    axis.set_xlim(left=0.05)
    axis.set_ylim(0, 100)
    axis.set_xlabel("Energy per session (kWh, log scale)")
    axis.set_ylabel("Cumulative share of sampled sessions (%)")
    axis.set_title("Distribution of delivered energy per charging session")
    axis.legend(frameon=False)
    axis.text(
        0.99,
        0.03,
        "Deterministic sample; zero-energy sessions omitted",
        transform=axis.transAxes,
        ha="right",
        color="#666666",
        fontsize=9,
    )
    figure.tight_layout()
    figure.savefig(FIGURE_DIR / "04-session-energy-distribution.png", bbox_inches="tight")
    plt.close(figure)


def plot_utilization_distribution(stations: pd.DataFrame) -> None:
    figure, axis = plt.subplots(figsize=(10, 5))
    bins = np.linspace(0, 1, 51)
    for month in ORDER_FILES:
        values = stations.loc[
            stations["month"] == month, "monthly_gun_utilization_rate"
        ].dropna()
        axis.hist(
            values,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2,
            color=MONTH_COLORS[month],
            label=MONTH_LABELS[month],
        )

    axis.set_xlabel("Monthly charging-gun utilization rate")
    axis.set_ylabel("Density")
    axis.set_title("Distribution of monthly charging-gun utilization")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(FIGURE_DIR / "05-utilization-distribution.png", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    missing = [path for path in [*ORDER_FILES.values(), STATION_FILE] if not path.exists()]
    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise SystemExit(f"Missing required data files:\n{missing_text}")

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    set_chart_style()
    monthly, hourly, site_summary, energy_samples = collect_order_summaries()
    stations = pd.read_parquet(STATION_FILE)
    stations["construction_site"] = stations["construction_site"].map(normalize_site)

    plot_monthly_overview(monthly)
    plot_hourly_profile(hourly)
    plot_site_mix(site_summary)
    plot_energy_distribution(energy_samples)
    plot_utilization_distribution(stations)

    print(f"Created 5 charts in {FIGURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

