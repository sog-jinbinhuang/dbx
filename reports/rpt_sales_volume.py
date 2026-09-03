"""
production_volume_report.py
============================
Monthly sales-volume (kg) tracker by product, for production planning.

Source : FCT_GLOBAL_SALES_ORDERS_3 (transactional order/invoice-line grain)
Volume : QTY_IN_KG
Month  : YEAR_MONTH_DATE (the table's pre-built year+month bucket)

Actual vs. open orders is split on SALES_OR_ORDER:
  'ORDER' (case-insensitive)  -> open order, not yet shipped
  anything else               -> actual / historical volume

Each row is keyed on (PRODUCT_NAME, PROD_PKG_CODE) -- i.e. a product name
plus its package code, since the same product name can span more than one
package configuration. Rows are sorted by PROD_PKG_CODE, then PRODUCT_NAME.

Tabs produced
-------------
  SUMMARY               — one row per product across ALL databases: 12-mo
                           actual total, monthly average, open-order total,
                           grand total
  <DATABASE> ACTUAL      — one tab per DATABASE value: product x trailing-
                           12-month matrix (shipped/actual). Each product row
                           can be expanded (Excel outline grouping) to reveal
                           the customers contributing to it, each with its
                           own monthly breakdown.
  <DATABASE> OPEN         — same, but for open / not-yet-shipped orders.

Run:  python production_volume_report.py

Requires env vars:
  DATABRICKS_SERVER_HOSTNAME   e.g. adb-1234567890123456.7.azuredatabricks.net
  DATABRICKS_HTTP_PATH         e.g. /sql/1.0/warehouses/abc123def456
  DATABRICKS_TOKEN             a personal access token
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
from databricks import sql as databricks_sql
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook as WorkbookType


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

_DIR = os.path.dirname(os.path.abspath(__file__))

DBX_SERVER_HOSTNAME = os.environ["DATABRICKS_SERVER_HOSTNAME"]
DBX_HTTP_PATH       = os.environ["DATABRICKS_HTTP_PATH"]
DBX_ACCESS_TOKEN    = os.environ["DATABRICKS_TOKEN"]

DBX_CATALOG = "dev"
DBX_SCHEMA  = "gold_sales"

TODAY        = date.today()
_DATE_SUFFIX = TODAY.strftime("%m%d%Y")
OUTPUT_FILE  = os.path.join(_DIR, f"production_volume_report_{_DATE_SUFFIX}.xlsx")

# Value in SALES_OR_ORDER that marks a row as an OPEN order (not yet shipped).
# Everything else is treated as actual / historical volume. Matched case-insensitively.
OPEN_ORDER_VALUE = "ORDER"

# How many completed calendar months of ACTUAL history to show, ending with
# the current month, applied uniformly across every database's ACTUAL tab so
# they stay comparable. Open orders show whatever months exist per database
# (no upper bound on the query, so future months are unaffected).
HISTORY_MONTHS = 12

# Buffer on the SQL date filter so HISTORY_MONTHS isn't clipped right at a
# month boundary. NOTE: this also becomes the floor for open orders — an open
# order dated more than SQL_LOOKBACK_MONTHS in the past won't be pulled in.
# Bump this up if overdue backlog older than ~13 months is a real scenario.
SQL_LOOKBACK_MONTHS = HISTORY_MONTHS + 1


# ═══════════════════════════════════════════════════════════════════════════
# STYLESHEET (kept intentionally small — this is a standalone script)
# ═══════════════════════════════════════════════════════════════════════════

class S:
    # Soft slate-blue accent (Office "Text 2") instead of a heavy dark-navy
    # block, with light tinted fills rather than solid saturated colors.
    TITLE_BG   = "44546A"; TITLE_FG   = "FFFFFF"; SUBTITLE_FG = "D6DCE5"
    HDR_BG     = "D9E2F3"; HDR_FG     = "44546A"
    PROD_BG    = "EDF1F8"; PROD_FG    = "44546A"   # product (group header) rows
    CUST_EVEN  = "FFFFFF"; CUST_ODD   = "F8F9FB"; CUST_FG = "404040"  # customer (detail) rows
    GRAND_BG   = "44546A"; GRAND_FG   = "FFFFFF"

    # Whole kg, thousands-separated, zero shown as a dash, negatives with a
    # leading minus — no more "37,739." trailing-dot noise from stray decimals.
    NUM_FMT = '#,##0;-#,##0;"-"'

    SEP       = Side(style="thin", color="AAB8CC")  # subtle divider (label / total cols)
    GROUP_DIV = Side(style="hair", color="E2E5EA")  # hairline between product groups
    OUTER     = Side(style="thin", color="8EA9C1")  # table border

    @staticmethod
    def fill(hex_color: str) -> PatternFill:
        return PatternFill("solid", fgColor=hex_color)

    @staticmethod
    def font(bold: bool = False, color: str = "404040", size: int = 9,
             italic: bool = False) -> Font:
        return Font(name="Calibri", bold=bold, color=color, size=size, italic=italic)

    @staticmethod
    def align(h: str = "right", wrap: bool = False) -> Alignment:
        return Alignment(horizontal=h, vertical="center", wrap_text=wrap)

    @classmethod
    def right_sep(cls) -> Border:
        return Border(right=cls.SEP)

    @classmethod
    def apply_outer_border(cls, ws, r1: int, r2: int, c1: int, c2: int) -> None:
        for r in range(r1, r2 + 1):
            lc, rc = ws.cell(row=r, column=c1), ws.cell(row=r, column=c2)
            lc.border = Border(left=cls.OUTER, top=lc.border.top,
                               bottom=lc.border.bottom, right=lc.border.right)
            rc.border = Border(right=cls.OUTER, top=rc.border.top,
                               bottom=rc.border.bottom, left=rc.border.left)
        for c in range(c1, c2 + 1):
            tc, bc = ws.cell(row=r1, column=c), ws.cell(row=r2, column=c)
            tc.border = Border(top=cls.OUTER, left=tc.border.left,
                               right=tc.border.right, bottom=tc.border.bottom)
            bc.border = Border(bottom=cls.OUTER, left=bc.border.left,
                               right=bc.border.right, top=bc.border.top)


def period_label(p: pd.Period) -> str:
    return p.strftime("%b %Y")


def safe_sheet_name(base: str, suffix: str) -> str:
    """Sanitize + truncate a sheet name so `base + suffix` fits Excel's 31-char limit."""
    max_base = 31 - len(suffix)
    cleaned = (str(base)[:max_base]
               .replace("/", "-").replace("\\", "-")
               .replace("*", "").replace("?", "")
               .replace("[", "").replace("]", "")
               .replace(":", "").strip().upper())
    return f"{cleaned}{suffix}"


# ═══════════════════════════════════════════════════════════════════════════
# LOADER
# ═══════════════════════════════════════════════════════════════════════════

class Loader:
    """Connects to Databricks and pulls product/customer/month/volume rows."""

    def __init__(self) -> None:
        print(f"Connecting to Databricks ({DBX_SERVER_HOSTNAME}) ...")
        self._conn = databricks_sql.connect(
            server_hostname = DBX_SERVER_HOSTNAME,
            http_path        = DBX_HTTP_PATH,
            access_token     = DBX_ACCESS_TOKEN,
            catalog          = DBX_CATALOG,
            schema           = DBX_SCHEMA,
        )
        print("  Connected.")

    def close(self) -> None:
        self._conn.close()
        print("  Databricks connection closed.")

    def load(self) -> pd.DataFrame:
        print("  Loading FCT_GLOBAL_SALES_ORDERS_3 ...")
        cur = self._conn.cursor()
        cur.execute(f"""
            SELECT
                product_name,
                prod_pkg_code,
                database,
                cust_code,
                cust_name,
                sales_or_order,
                year_month_date,
                qty_in_kg
            FROM FCT_GLOBAL_SALES_ORDERS_3
            WHERE year_month_date >= add_months(
                -- trunc(date, 'MM') is Databricks' month-truncation for a DATE
                -- (date_trunc() expects/returns a TIMESTAMP instead).
                -- The America/New_York conversion matches what fct_global_backlog.sql
                -- needed: Databricks warehouses default to UTC, while this pipeline
                -- ran in America/New_York on Snowflake, so a bare current_date()
                -- can silently roll into the next day (and near month-end, the
                -- wrong month) once UTC has passed midnight local time.
                trunc(cast(from_utc_timestamp(current_timestamp(), 'America/New_York') as date), 'MM'),
                -{SQL_LOOKBACK_MONTHS}
            )
        """)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        df = pd.DataFrame(rows, columns=cols)
        print(f"    {len(df):,} rows")

        df["QTY_IN_KG"] = pd.to_numeric(df["QTY_IN_KG"], errors="coerce").fillna(0)
        for col in ("PRODUCT_NAME", "PROD_PKG_CODE", "DATABASE",
                    "CUST_CODE", "CUST_NAME", "SALES_OR_ORDER"):
            df[col] = (df[col].astype(str).str.strip()
                       .replace({"nan": "", "None": ""}).fillna(""))

        df["YEAR_MONTH_DATE"] = pd.to_datetime(df["YEAR_MONTH_DATE"], errors="coerce")
        df["_PERIOD"]  = df["YEAR_MONTH_DATE"].dt.to_period("M")
        df["_IS_OPEN"] = df["SALES_OR_ORDER"].str.upper() == OPEN_ORDER_VALUE.upper()

        # Drop rows with no product name, no database, or no resolvable month.
        df = df[(df["PRODUCT_NAME"] != "") & (df["DATABASE"] != "") & df["_PERIOD"].notna()]
        return df


# ═══════════════════════════════════════════════════════════════════════════
# TRANSFORM
# ═══════════════════════════════════════════════════════════════════════════

def build_month_index() -> pd.PeriodIndex:
    """Trailing HISTORY_MONTHS calendar months, ending with the current month."""
    current_period = pd.Timestamp(TODAY).to_period("M")
    return pd.period_range(end=current_period, periods=HISTORY_MONTHS, freq="M")


def _restrict_and_order(df: pd.DataFrame, months: pd.PeriodIndex | None):
    """Shared month-filtering logic for both pivot builders below."""
    if months is not None:
        df = df[df["_PERIOD"].isin(months)]
        col_order = months
    else:
        col_order = sorted(df["_PERIOD"].dropna().unique())
    return df, col_order


def build_product_pivot(df: pd.DataFrame, months: pd.PeriodIndex | None) -> pd.DataFrame:
    """
    (PRODUCT_NAME, PROD_PKG_CODE) x month matrix of summed QTY_IN_KG, plus
    a '_TOTAL' column. Used for the cross-database SUMMARY tab.
    """
    if df.empty:
        return pd.DataFrame()
    df, col_order = _restrict_and_order(df, months)
    if df.empty:
        return pd.DataFrame()
    pivot = (df.groupby(["PRODUCT_NAME", "PROD_PKG_CODE", "_PERIOD"])["QTY_IN_KG"]
             .sum().unstack("_PERIOD"))
    pivot = pivot.reindex(columns=col_order, fill_value=0).fillna(0)
    pivot["_TOTAL"] = pivot.sum(axis=1)
    return pivot


def build_detail_pivot(df: pd.DataFrame, months: pd.PeriodIndex | None) -> pd.DataFrame:
    """
    (PRODUCT_NAME, PROD_PKG_CODE, CUST_NAME) x month matrix of summed
    QTY_IN_KG, plus a '_TOTAL' column. Used for the per-database tabs —
    product rows are derived by summing the customer rows beneath them.
    """
    if df.empty:
        return pd.DataFrame()
    df, col_order = _restrict_and_order(df, months)
    if df.empty:
        return pd.DataFrame()
    pivot = (df.groupby(["PRODUCT_NAME", "PROD_PKG_CODE", "CUST_NAME", "_PERIOD"])["QTY_IN_KG"]
             .sum().unstack("_PERIOD"))
    pivot = pivot.reindex(columns=col_order, fill_value=0).fillna(0)
    pivot["_TOTAL"] = pivot.sum(axis=1)
    return pivot


def iter_products_sorted(detail_pivot: pd.DataFrame):
    """
    Yield (product_name, pkg_code, customer_subframe) for a build_detail_pivot()
    result, in PROD_PKG_CODE -> PRODUCT_NAME order. Customers within each
    product are sorted by their total volume, descending.
    """
    if detail_pivot.empty:
        return
    product_keys = (detail_pivot.index.to_frame(index=False)
                     [["PRODUCT_NAME", "PROD_PKG_CODE"]]
                     .drop_duplicates()
                     .sort_values(["PROD_PKG_CODE", "PRODUCT_NAME"]))
    for _, key in product_keys.iterrows():
        pname, pkg = key["PRODUCT_NAME"], key["PROD_PKG_CODE"]
        sub = detail_pivot.xs((pname, pkg), level=("PRODUCT_NAME", "PROD_PKG_CODE"))
        sub = sub.sort_values("_TOTAL", ascending=False)
        yield pname, pkg, sub


def build_summary(actual_pivot: pd.DataFrame, open_pivot: pd.DataFrame) -> pd.DataFrame:
    actual_total = actual_pivot["_TOTAL"] if not actual_pivot.empty else pd.Series(dtype=float)
    open_total   = open_pivot["_TOTAL"]   if not open_pivot.empty   else pd.Series(dtype=float)
    keys = set(actual_total.index) | set(open_total.index)

    rows = []
    for pname, pkg in keys:
        a = float(actual_total.get((pname, pkg), 0))
        o = float(open_total.get((pname, pkg), 0))
        rows.append({
            "PRODUCT_NAME":       pname,
            "PROD_PKG_CODE":      pkg,
            "AVG_MONTHLY_ACTUAL": a / HISTORY_MONTHS,
            "TOTAL_ACTUAL":       a,
            "TOTAL_OPEN":         o,
            "GRAND_TOTAL":        a + o,
        })
    return (pd.DataFrame(rows)
            .sort_values(["PROD_PKG_CODE", "PRODUCT_NAME"])
            .reset_index(drop=True))


# ═══════════════════════════════════════════════════════════════════════════
# WRITERS
# ═══════════════════════════════════════════════════════════════════════════

def _title_banner(ws, n_cols: int, title: str, subtitle: str) -> None:
    ws.sheet_view.showGridLines = False  # rely on our own borders/banding, not Excel's default grid
    for row, text, size in [(1, title, 11), (2, subtitle, 9)]:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
        c = ws.cell(row=row, column=1, value=text)
        c.font = S.font(bold=(row == 1), color=S.TITLE_FG if row == 1 else S.SUBTITLE_FG, size=size)
        c.fill = S.fill(S.TITLE_BG)
        c.alignment = S.align("center")
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 14


def write_summary_tab(wb: WorkbookType, summary_df: pd.DataFrame,
                      months: pd.PeriodIndex, open_periods: list) -> None:
    ws = wb.create_sheet("SUMMARY", index=0)
    headers = ["Product Name", "Package Code", "Avg Monthly (kg)",
               "Total Actual 12-Mo (kg)", "Total Open Orders (kg)", "Grand Total (kg)"]
    n_cols = len(headers)

    span      = f"{period_label(months[0])} - {period_label(months[-1])}"
    open_span = (f"{period_label(open_periods[0])} - {period_label(open_periods[-1])}"
                 if open_periods else "none")
    _title_banner(
        ws, n_cols,
        f"Production Volume Summary — All Databases  |  {TODAY.strftime('%B %d, %Y')}",
        f"Actual: {span}   |   Open orders: {open_span}   |   Sorted by Package Code",
    )

    hdr_row = 3
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=hdr_row, column=ci, value=h)
        c.font = S.font(bold=True, color=S.HDR_FG)
        c.fill = S.fill(S.HDR_BG)
        c.alignment = S.align("center", wrap=True)
        if ci == 2:  # separator after the label columns
            c.border = S.right_sep()
    ws.row_dimensions[hdr_row].height = 28

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 16
    for col in ("C", "D", "E", "F"):
        ws.column_dimensions[col].width = 18

    cur = hdr_row + 1
    totals = {"AVG_MONTHLY_ACTUAL": 0.0, "TOTAL_ACTUAL": 0.0,
              "TOTAL_OPEN": 0.0, "GRAND_TOTAL": 0.0}
    for i, r in summary_df.iterrows():
        bg = S.CUST_ODD if i % 2 == 1 else S.CUST_EVEN
        vals = [r["PRODUCT_NAME"], r["PROD_PKG_CODE"], r["AVG_MONTHLY_ACTUAL"],
                r["TOTAL_ACTUAL"], r["TOTAL_OPEN"], r["GRAND_TOTAL"]]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(row=cur, column=ci, value=v)
            c.font = S.font(bold=(ci == 6))
            c.fill = S.fill(bg)
            if ci == 1:
                c.alignment = S.align("left")
            elif ci == 2:
                c.alignment = S.align("center")
                c.border = S.right_sep()
            else:
                c.alignment = S.align("right")
                c.number_format = S.NUM_FMT
        cur += 1
        for k in totals:
            totals[k] += r[k]

    c = ws.cell(row=cur, column=1, value="GRAND TOTAL")
    c.font, c.fill, c.alignment = S.font(bold=True, color=S.GRAND_FG), S.fill(S.GRAND_BG), S.align("left")
    c2 = ws.cell(row=cur, column=2)
    c2.fill, c2.border = S.fill(S.GRAND_BG), S.right_sep()
    for ci, key in zip(range(3, 7),
                       ["AVG_MONTHLY_ACTUAL", "TOTAL_ACTUAL", "TOTAL_OPEN", "GRAND_TOTAL"]):
        c = ws.cell(row=cur, column=ci, value=totals[key])
        c.number_format = S.NUM_FMT
        c.font, c.fill, c.alignment = S.font(bold=True, color=S.GRAND_FG), S.fill(S.GRAND_BG), S.align("right")

    S.apply_outer_border(ws, 1, cur, 1, n_cols)
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A{hdr_row}:{get_column_letter(n_cols)}{hdr_row}"


def write_detail_tab(wb: WorkbookType, sheet_name: str, title: str, subtitle: str,
                     detail_pivot: pd.DataFrame) -> None:
    """
    Product x month matrix for one database. Each product is a visible group
    header row; the customers contributing to it are written as hidden,
    outline-grouped rows directly beneath (Excel's [+] expands them).
    """
    ws = wb.create_sheet(sheet_name)

    if detail_pivot.empty:
        ws.cell(row=1, column=1, value=f"{title} — no data in range")
        return

    periods = [c for c in detail_pivot.columns if c != "_TOTAL"]
    n_cols  = 2 + len(periods) + 1  # Product Name, Package Code, months..., Total

    _title_banner(ws, n_cols, title, subtitle)

    hdr_row = 3
    headers = ["Product Name", "Package Code"] + [period_label(p) for p in periods] + ["Total (kg)"]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=hdr_row, column=ci, value=h)
        c.font = S.font(bold=True, color=S.HDR_FG)
        c.fill = S.fill(S.HDR_BG)
        c.alignment = S.align("center", wrap=True)
        if ci == 2 or ci == n_cols - 1:  # separators: after labels, and before Total
            c.border = S.right_sep()
    ws.row_dimensions[hdr_row].height = 22

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 14
    for ci in range(3, n_cols + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 12

    cur = hdr_row + 1
    col_totals  = [0.0] * len(periods)
    grand_total = 0.0

    total_col_idx = n_cols - 1  # last period column, gets the pre-Total separator

    for pname, pkg, cust_sub in iter_products_sorted(detail_pivot):
        prod_month_totals = cust_sub[periods].sum()
        prod_total = float(cust_sub["_TOTAL"].sum())

        # Product row (group header — stays visible when collapsed)
        c = ws.cell(row=cur, column=1, value=pname)
        c.font, c.fill, c.alignment = S.font(bold=True, color=S.PROD_FG), S.fill(S.PROD_BG), S.align("left")
        c = ws.cell(row=cur, column=2, value=pkg)
        c.font, c.fill, c.alignment = S.font(bold=True, color=S.PROD_FG), S.fill(S.PROD_BG), S.align("center")
        c.border = S.right_sep()
        for pi, p in enumerate(periods):
            v = float(prod_month_totals[p])
            col_totals[pi] += v
            col = 3 + pi
            c = ws.cell(row=cur, column=col, value=v)
            c.number_format = S.NUM_FMT
            c.font, c.fill, c.alignment = S.font(bold=True, color=S.PROD_FG), S.fill(S.PROD_BG), S.align("right")
            if col == total_col_idx:
                c.border = S.right_sep()
        c = ws.cell(row=cur, column=n_cols, value=prod_total)
        c.number_format = S.NUM_FMT
        c.font, c.fill, c.alignment = S.font(bold=True, color=S.PROD_FG), S.fill(S.PROD_BG), S.align("right")
        grand_total += prod_total
        prod_row = cur
        cur += 1

        # Customer sub-rows (hidden by default, expand via the outline [+])
        last_row_in_group = prod_row
        for ci_idx, (cust_name, cust_row) in enumerate(cust_sub.iterrows()):
            bg = S.CUST_ODD if ci_idx % 2 == 1 else S.CUST_EVEN
            label = cust_name if cust_name else "(unspecified customer)"
            c = ws.cell(row=cur, column=1, value=f"    {label}")
            c.font, c.fill, c.alignment = S.font(italic=True), S.fill(bg), S.align("left")
            c2 = ws.cell(row=cur, column=2)
            c2.fill, c2.border = S.fill(bg), S.right_sep()
            for pi, p in enumerate(periods):
                col = 3 + pi
                c = ws.cell(row=cur, column=col, value=float(cust_row[p]))
                c.number_format = S.NUM_FMT
                c.font, c.fill, c.alignment = S.font(italic=True), S.fill(bg), S.align("right")
                if col == total_col_idx:
                    c.border = S.right_sep()
            c = ws.cell(row=cur, column=n_cols, value=float(cust_row["_TOTAL"]))
            c.number_format = S.NUM_FMT
            c.font, c.fill, c.alignment = S.font(italic=True), S.fill(bg), S.align("right")

            ws.row_dimensions[cur].outline_level = 1
            ws.row_dimensions[cur].hidden = False  # visible by default; still collapsible via Excel's outline [-]
            last_row_in_group = cur
            cur += 1

        # Thin divider under the last row of this product's group (visible
        # whether or not the group is expanded) to separate it from the next.
        for col in range(1, n_cols + 1):
            cell = ws.cell(row=last_row_in_group, column=col)
            cell.border = Border(left=cell.border.left, right=cell.border.right,
                                 top=cell.border.top, bottom=S.GROUP_DIV)

    # Grand total row
    c = ws.cell(row=cur, column=1, value="GRAND TOTAL")
    c.font, c.fill, c.alignment = S.font(bold=True, color=S.GRAND_FG), S.fill(S.GRAND_BG), S.align("left")
    c2 = ws.cell(row=cur, column=2)
    c2.fill, c2.border = S.fill(S.GRAND_BG), S.right_sep()
    for pi in range(len(periods)):
        col = 3 + pi
        c = ws.cell(row=cur, column=col, value=col_totals[pi])
        c.number_format = S.NUM_FMT
        c.font, c.fill, c.alignment = S.font(bold=True, color=S.GRAND_FG), S.fill(S.GRAND_BG), S.align("right")
        if col == total_col_idx:
            c.border = S.right_sep()
    c = ws.cell(row=cur, column=n_cols, value=grand_total)
    c.number_format = S.NUM_FMT
    c.font, c.fill, c.alignment = S.font(bold=True, color=S.GRAND_FG), S.fill(S.GRAND_BG), S.align("right")

    S.apply_outer_border(ws, 1, cur, 1, n_cols)
    ws.sheet_properties.outlinePr.summaryBelow = False  # group header sits above its hidden children
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A{hdr_row}:{get_column_letter(n_cols)}{hdr_row}"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    loader = Loader()
    try:
        df = loader.load()
    finally:
        loader.close()

    months = build_month_index()

    # ---- SUMMARY: cross-database totals, product-level only ----
    actual_all = build_product_pivot(df[~df["_IS_OPEN"]], months)
    open_all   = build_product_pivot(df[df["_IS_OPEN"]], None)
    summary_df = build_summary(actual_all, open_all)
    open_periods_all = [c for c in open_all.columns if c != "_TOTAL"] if not open_all.empty else []

    wb = Workbook()
    wb.remove(wb.active)
    write_summary_tab(wb, summary_df, months, open_periods_all)

    # ---- one ACTUAL + one OPEN tab per DATABASE, with customer drill-down ----
    databases = sorted(d for d in df["DATABASE"].unique() if d)
    print(f"  Databases found: {databases}")

    for db in databases:
        db_df = df[df["DATABASE"] == db]

        actual_detail = build_detail_pivot(db_df[~db_df["_IS_OPEN"]], months)
        write_detail_tab(
            wb, safe_sheet_name(db, " ACTUAL"),
            f"{db} — Actual Volume by Product  |  {TODAY.strftime('%B %d, %Y')}",
            f"Shipped/booked volume in kg by product & customer, "
            f"{period_label(months[0])} - {period_label(months[-1])}",
            actual_detail,
        )

        open_detail = build_detail_pivot(db_df[db_df["_IS_OPEN"]], None)
        open_periods_db = [c for c in open_detail.columns if c != "_TOTAL"] if not open_detail.empty else []
        open_subtitle = "Not-yet-shipped order volume in kg by product & customer"
        if open_periods_db:
            open_subtitle += f", {period_label(open_periods_db[0])} - {period_label(open_periods_db[-1])}"
        write_detail_tab(
            wb, safe_sheet_name(db, " OPEN"),
            f"{db} — Open Orders by Product  |  {TODAY.strftime('%B %d, %Y')}",
            open_subtitle,
            open_detail,
        )

    wb.save(OUTPUT_FILE)
    print(f"\nSaved -> {OUTPUT_FILE}")
    print(f"Tabs: {[ws.title for ws in wb.worksheets]}")
    print(f"Products (summary): {len(summary_df)}  |  Databases: {len(databases)}  |  "
          f"Actual window: {len(months)} months")


if __name__ == "__main__":
    main()