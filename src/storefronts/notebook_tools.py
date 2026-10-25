"""Shared notebook presentation, without hidden database definitions."""

from pprint import pprint

import matplotlib.pyplot as plt
import pandas as pd
from IPython.display import display

from storefronts.gold import pipeline, query

SOURCE = "Source: NYC DCWP archive + live; audited storefront visit records."


def table(name, collection="visit_features", **kwargs):
    pprint(pipeline(name, **kwargs), width=100, sort_dicts=False)
    rows = query(name, collection, **kwargs)
    frame = pd.json_normalize(rows)
    frame.columns = [c.removeprefix("_id.") for c in frame.columns]
    display(frame)
    return frame


def style():
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.figsize": (11, 5),
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 110,
        }
    )
    pd.set_option("display.max_rows", 80)
    pd.set_option("display.max_columns", 30)


def finish(ax, title, xlabel, ylabel):
    ax.set(title=title, xlabel=xlabel, ylabel=ylabel)
    ax.figure.text(0.01, 0.01, SOURCE, fontsize=8)
    ax.figure.tight_layout(rect=(0, 0.045, 1, 1))
    plt.show()
