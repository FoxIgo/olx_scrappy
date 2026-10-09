#!/usr/bin/env python3
"""Load a `scrappy q export` table into a pandas DataFrame and evaluate an expression.

Run it through uv so pandas is available without being a project dependency:

    uv run --with pandas python <skill-dir>/scripts/frame.py <export.csv> "<expression>"

The expression is evaluated with `df` (the DataFrame) and `pd` in scope, e.g.:

    "df.groupby('attr_ram_gb')['price'].median()"
    "pd.crosstab(df['attr_gpu'], df['attr_condition'])"
    "df.assign(pln_per_gb=df['price'] / df['attr_ram_gb']).nsmallest(10, 'pln_per_gb')[['offer_id','title','price','attr_ram_gb']]"

Without an expression it prints a compact profile: shape, columns with dtype and
non-null counts, and the numeric summary. Preparation done on load:
- `price` = numeric copy of `price_amount`, only for rows with price_kind == "fixed"
  (exchange/free offers get NaN, so they can't distort statistics).
- `attr_*` columns that are entirely numeric are converted to numbers.
- Timestamp columns (`*_at`) are parsed as UTC datetimes.
Output is plain text, sized for reading in a terminal. Wide results are truncated by
pandas display limits; select columns explicitly to keep them small.
"""

from __future__ import annotations

import sys

try:
    import pandas as pd
except ImportError:  # pragma: no cover - guidance for the caller
    sys.exit("pandas is not available; run via: uv run --with pandas python frame.py ...")


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    if "price_amount" in df.columns:
        fixed = df.get("price_kind", pd.Series(["fixed"] * len(df))).eq("fixed")
        df["price"] = pd.to_numeric(df["price_amount"], errors="coerce").where(fixed)
    for col in [c for c in df.columns if c.startswith("attr_")]:
        converted = pd.to_numeric(df[col], errors="coerce")
        if df[col].notna().sum() and converted.notna().sum() == df[col].notna().sum():
            df[col] = converted
    for col in [c for c in df.columns if c.endswith("_at")]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    for col in ("relevant", "negotiable"):
        if col in df.columns:
            df[col] = df[col].map({"true": True, "false": False, "True": True, "False": False})
    return df


def profile(df: pd.DataFrame) -> str:
    lines = [f"shape: {df.shape[0]} rows x {df.shape[1]} columns", "columns:"]
    for col in df.columns:
        lines.append(f"  {col}: {df[col].dtype}, non-null {int(df[col].notna().sum())}")
    numeric = df.select_dtypes("number")
    if not numeric.empty:
        lines += ["numeric summary:", numeric.describe().round(2).to_string()]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.max_rows", 60)
    df = load(argv[0])
    if len(argv) == 1:
        print(profile(df))
        return 0
    result = eval(argv[1], {"pd": pd}, {"df": df})  # noqa: S307 - local analysis helper
    print(result.to_string() if hasattr(result, "to_string") else result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
