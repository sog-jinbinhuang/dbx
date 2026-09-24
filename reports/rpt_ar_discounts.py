"""
rpt_ar_discounts.py
====================
Discount tracking report from FCT_GLOBAL_AR_DISCOUNTS (dbt model, built on
top of ARCASH) -- tracks discount amounts applied per database, customer,
and posting period (year/month).

Tabs produced
-------------
  BY CUSTOMER    -- pivot: one row per (database, customer), one column
                    per month, plus a Total column
  <DATABASE> Detail -- one tab per database: flat, sortable list of every
                    discount transaction in that database
"""

from __future__ import annotations

import io
import os
from datetime import date

import pandas as pd
from databricks import sql as databricks_sql
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

_DIR = os.path.dirname(os.path.abspath(__file__))

DBX_SERVER_HOSTNAME = os.environ["DATABRICKS_SERVER_HOSTNAME"]
DBX_HTTP_PATH       = os.environ["DATABRICKS_HTTP_PATH"]
DBX_ACCESS_TOKEN    = os.environ["DATABRICKS_TOKEN"]
DBX_CATALOG         = "dev"
DBX_SCHEMA          = "gold_finance"

MODEL_NAME = "FCT_GLOBAL_AR_DISCOUNTS"

TODAY        = date.today()
_DATE_SUFFIX = TODAY.strftime("%m%d%Y")
OUTPUT_FILE  = os.path.join(_DIR, f"ar_discounts_report_{_DATE_SUFFIX}.xlsx")

NUM_USD = "#,##0.00;-#,##0.00"

DETAIL_COLS: list[tuple[str, int, str, str, str]] = [
    # (header, col_width, source_key, number_format, halign)
    ("Year-Period",      12, "YEAR_PERIOD",       "@",          "center"),
    ("Customer",         28, "CUST_NAME",         "@",          "left"),
    ("Terms Description",24, "TERMS_DESCRIPTION",          "@",        "left"),
    ("Cust Code",        10, "CUST_CODE",         "@",          "center"),
    ("Discount Amt",     14, "DISCOUNT_AMT",      NUM_USD,      "right"),
    ("Ref #",            12, "REF_NUM",           "@",          "center"),
    ("Ref Type",         10, "REF_TYPE",          "@",          "center"),
    ("Payment Method",   16, "PAYMENT_METHOD",    "@",          "left"),
    ("Due Date",         13, "DUE_DATE",          "MM/DD/YYYY", "center"),
    ("Payment Date",     13, "PAYMENT_DATE",      "MM/DD/YYYY", "center"),
    ("Journal #",        14, "JOURNAL_NUMBER",    "@",          "center"),
    ("Created By",       16, "CREATED_BY",        "@",          "left"),
]

DATE_COLS = {"DUE_DATE", "PAYMENT_DATE"}


# ═══════════════════════════════════════════════════════════════════════════════
# STYLESHEET -- lighter slate-blue theme, matching the other converted reports
# ═══════════════════════════════════════════════════════════════════════════════

class S:
    TITLE_BG = "34495E"; TITLE_FG = "FFFFFF"
    COL_BG   = "DCE6F1"; COL_FG   = "000000"
    GRAND_BG = "34495E"; GRAND_FG = "FFFFFF"
    ALT_BG   = "F7F9FC"; EVEN_BG  = "FFFFFF"
    OUTER    = Side(style="medium", color="6C7A89")
    THIN     = Side(style="thin",   color="B0BAC5")
    THIN_G   = Side(style="thin",   color="E1E5EA")

    @staticmethod
    def fill(h: str) -> PatternFill: return PatternFill("solid", fgColor=h)
    @staticmethod
    def font(bold=False, color="000000", size=9, italic=False) -> Font:
        return Font(name="Arial", bold=bold, color=color, size=size, italic=italic)
    @staticmethod
    def align(h="right", v="center", wrap=False) -> Alignment:
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    @classmethod
    def apply_outer_border(cls, ws: Worksheet,
                           r1: int, r2: int, c1: int, c2: int) -> None:
        for r in range(r1, r2 + 1):
            lc = ws.cell(row=r, column=c1)
            rc = ws.cell(row=r, column=c2)
            lc.border = Border(left=cls.OUTER,  top=lc.border.top,
                               bottom=lc.border.bottom, right=lc.border.right)
            rc.border = Border(right=cls.OUTER, top=rc.border.top,
                               bottom=rc.border.bottom, left=rc.border.left)


# ═══════════════════════════════════════════════════════════════════════════════
# LOADER
# ═══════════════════════════════════════════════════════════════════════════════

class Loader:
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
        # "DATABASE" is a reserved word -- backtick-quoted, matching the
        # same fix used in order_audit.py.
        query = f"""
            SELECT
                `DATABASE`  AS DATABASE,
                CUST_NAME,
                TERMS_DESCRIPTION,
                CUST_CODE,
                POSTING_YEAR,
                POSTING_PERIOD,
                YEAR_PERIOD,
                DISCOUNT_AMT,
                REF_NUM,
                REF_TYPE,
                PAYMENT_METHOD,
                DUE_DATE,
                PAYMENT_DATE,
                JOURNAL_NUMBER,
                CREATED_BY
            FROM {MODEL_NAME}
        """
        print(f"  Loading {MODEL_NAME} ...")
        cur = self._conn.cursor()
        cur.execute(query)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()

        df = pd.DataFrame(rows, columns=cols)
        print(f"    {len(df):,} rows returned")

        df["DISCOUNT_AMT"] = pd.to_numeric(df["DISCOUNT_AMT"], errors="coerce").fillna(0)
        for col in ["DUE_DATE", "PAYMENT_DATE"]:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        for col in ["DATABASE", "CUST_NAME", "TERMS_DESCRIPTION",
                    "CUST_CODE", "REF_NUM", "REF_TYPE",
                    "PAYMENT_METHOD", "JOURNAL_NUMBER", "CREATED_BY", "YEAR_PERIOD"]:
            df[col] = (df[col].astype(str).str.strip()
                       .replace({"nan": "", "None": ""}).fillna(""))

        # Sorted newest period first -- most useful default for a tracking report
        df = df.sort_values(
            ["YEAR_PERIOD", "DATABASE"], ascending=[False, True]
        ).reset_index(drop=True)
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

class ReportBuilder:

    def __init__(self, wb: Workbook, df: pd.DataFrame) -> None:
        self.wb = wb
        self.df = df

    def _sc(self, ws, row, col, value=None, *, bold=False, fg="000000",
            bg="FFFFFF", fmt=None, halign="right", border=None, italic=False):
        c = ws.cell(row=row, column=col, value=value)
        c.font      = S.font(bold=bold, color=fg, italic=italic)
        c.fill      = bg if isinstance(bg, PatternFill) else S.fill(bg)
        c.alignment = S.align(halign)
        if fmt    is not None: c.number_format = fmt
        if border is not None: c.border        = border
        return c

    def _title_banner(self, ws: Worksheet, total_cols: int,
                      title: str, subtitle: str) -> None:
        for row, text, bold, size, color in [
            (1, title,    True,  11, S.TITLE_FG),
            (2, subtitle, False,  9, S.COL_BG),
        ]:
            ws.merge_cells(start_row=row, start_column=1,
                           end_row=row,   end_column=total_cols)
            c = ws.cell(row=row, column=1, value=text)
            c.font      = S.font(bold=bold, color=color, size=size)
            c.fill      = S.fill(S.TITLE_BG)
            c.alignment = S.align("center")
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 14

    # ── per-database DETAIL tab ──────────────────────────────────────────────

    def build_database_tab(self, db: str) -> None:
        safe = (f"{db} Detail"[:31] or "UNKNOWN").replace("/", "-").replace("\\", "-")
        ws = self.wb.create_sheet(safe)
        db_df = self.df[self.df["DATABASE"] == db]
        N = len(DETAIL_COLS)

        amt_col = next(i + 1 for i, (_, _, k, _, _) in enumerate(DETAIL_COLS) if k == "DISCOUNT_AMT")

        self._title_banner(
            ws, N,
            f"AR Discount Detail  |  {db}  |  {TODAY.strftime('%B %d, %Y')}",
            f"{len(db_df):,} transactions  |  Sorted by Year-Period (newest first)  |  Source: {MODEL_NAME}",
        )

        for ci, (hdr, width, _, _, _) in enumerate(DETAIL_COLS, start=1):
            c = ws.cell(row=3, column=ci, value=hdr)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=S.THIN_G, right=S.THIN_G,
                                 top=S.OUTER,   bottom=S.OUTER)
            ws.column_dimensions[get_column_letter(ci)].width = width
        ws.row_dimensions[3].height = 20

        cur_row = 4
        grand_amt = 0.0
        for row_idx, (_, r) in enumerate(db_df.iterrows()):
            bg = S.ALT_BG if row_idx % 2 == 1 else S.EVEN_BG
            ws.row_dimensions[cur_row].height = 15
            for ci, (_, _, key, fmt, halign) in enumerate(DETAIL_COLS, start=1):
                val = r[key]
                if key in DATE_COLS:
                    val = val.date() if pd.notna(val) and hasattr(val, "date") else None
                c = ws.cell(row=cur_row, column=ci, value=val)
                c.font          = S.font(color="000000")
                c.fill          = S.fill(bg)
                c.alignment     = S.align(halign)
                c.number_format = fmt
                c.border        = Border(left=S.THIN_G, right=S.THIN_G, bottom=S.THIN_G)
            grand_amt += float(r["DISCOUNT_AMT"])
            cur_row += 1

        # Grand total row
        for ci in range(1, N + 1):
            c = ws.cell(row=cur_row, column=ci)
            c.fill   = S.fill(S.GRAND_BG)
            c.font   = S.font(bold=True, color=S.GRAND_FG)
            c.border = Border(top=S.OUTER, bottom=S.OUTER)
        ws.cell(row=cur_row, column=1, value="GRAND TOTAL").alignment = S.align("left")
        self._sc(ws, cur_row, amt_col, grand_amt, bold=True, fg=S.GRAND_FG, bg=S.GRAND_BG, fmt=NUM_USD)
        ws.row_dimensions[cur_row].height = 16

        S.apply_outer_border(ws, 1, cur_row, 1, N)
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:{get_column_letter(N)}{cur_row - 1}"
        print(f"  {safe}: {len(db_df):,} rows | ${grand_amt:,.0f}")

    # ── BY CUSTOMER tab: pivot, customer x month ──────────────────────────────

    @staticmethod
    def _month_label(year_period: str) -> str:
        """'202601' -> 'Jan 2026'. Falls back to the raw string if it
        doesn't parse as YYYYMM (keeps the tab from breaking on unexpected
        formats rather than raising)."""
        try:
            yr, mo = int(year_period[:4]), int(year_period[4:6])
            return date(yr, mo, 1).strftime("%b %Y")
        except (ValueError, IndexError):
            return year_period

    def build_customer_monthly_tab(self) -> None:
        ws = self.wb.create_sheet("BY CUSTOMER", index=0)
        df = self.df

        # All history -- no year cutoff.
        periods = sorted(
            (p for p in df["YEAR_PERIOD"].unique() if p),
            reverse=True,  # most recent month first (leftmost column)
        )
        month_labels = [self._month_label(p) for p in periods]

        # Column layout: Database, Customer, Payment Terms, Terms Code,
        # Terms Description, Total, then months (newest first)
        info_cols        = ["TERMS_DESCRIPTION"]
        info_headers     = ["Terms Description"]
        info_widths      = [24]
        total_col        = 3 + len(info_cols)
        month_col_start  = total_col + 1
        N = total_col + len(periods)

        self._title_banner(
            ws, N,
            f"AR Discount by Customer  |  Monthly  |  {TODAY.strftime('%B %d, %Y')}",
            f"{df['CUST_NAME'].nunique():,} customers  |  Source: {MODEL_NAME}",
        )

        # Header row
        header_cells = [("Database", 1), ("Customer", 2)]
        header_cells += list(zip(info_headers, range(3, 3 + len(info_cols))))
        header_cells += [("Total (USD)", total_col)]
        for text, col in header_cells:
            c = ws.cell(row=3, column=col, value=text)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=S.THIN_G, right=S.THIN_G,
                                 top=S.OUTER,   bottom=S.OUTER)
        ws.column_dimensions["A"].width = 12
        ws.column_dimensions["B"].width = 28
        for i, width in enumerate(info_widths):
            ws.column_dimensions[get_column_letter(3 + i)].width = width
        ws.column_dimensions[get_column_letter(total_col)].width = 15
        for i, label in enumerate(month_labels):
            col = month_col_start + i
            c = ws.cell(row=3, column=col, value=label)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=S.THIN_G, right=S.THIN_G,
                                 top=S.OUTER,   bottom=S.OUTER)
            ws.column_dimensions[get_column_letter(col)].width = 12
        ws.row_dimensions[3].height = 20

        # Pivot: (database, customer) rows x year_period columns, summed.
        # reindex to `periods` controls column order (newest first).
        pivot = (
            df.pivot_table(
                index=["DATABASE", "CUST_NAME"],
                columns="YEAR_PERIOD",
                values="DISCOUNT_AMT",
                aggfunc="sum",
                fill_value=0,
            )
            .reindex(columns=periods, fill_value=0)
        )
        pivot["TOTAL"] = pivot.sum(axis=1)
        pivot = pivot.reset_index()
        # Safety net: drop any all-zero rows (shouldn't normally occur, since
        # every customer here has at least one real discount by the model's
        # own filter, but harmless to keep).
        pivot = pivot[pivot["TOTAL"] != 0]

        # Terms/discount info is a per-customer attribute, not something to
        # sum -- pulled via a separate lookup (first non-blank/non-null value
        # seen per customer) and merged in, rather than folded into the
        # pivot's groupby index. Using the index would silently split a
        # customer into multiple rows if their terms value were ever
        # inconsistent across transactions; a lookup instead just picks one.
        #
        # Which columns are numeric is keyed off NUMERIC_INFO_COLS (by name)
        # rather than sniffed via pandas dtype -- an all-NaN/all-None slice
        # can register as 'object' dtype in some pandas groupby paths, which
        # would otherwise misclassify a genuinely-numeric column.
        NUMERIC_INFO_COLS = set()  # e.g. {"SOME_NUMERIC_FIELD"} -- none currently in info_cols

        def _first_valid(s: pd.Series):
            is_numeric = s.name in NUMERIC_INFO_COLS
            if is_numeric:
                nonblank = pd.to_numeric(s, errors="coerce").dropna()
            else:
                nonblank = s[(s != "") & s.notna()]
            if len(nonblank):
                return nonblank.iloc[0]
            return None if is_numeric else ""

        customer_info = (
            df.groupby(["DATABASE", "CUST_NAME"])[info_cols]
            .agg(_first_valid)
            .reset_index()
        )
        pivot = pivot.merge(customer_info, on=["DATABASE", "CUST_NAME"], how="left")

        # Sort by database ascending, then biggest total-discount customer
        # first within it.
        pivot = pivot.sort_values(["DATABASE", "TOTAL"], ascending=[True, False])

        # Positive amounts normal, zero shown as a dash -- easier to scan
        # a wide monthly grid than a wall of "0.00"s.
        ZERO_DASH_USD = '#,##0.00;-#,##0.00;"-"'

        cur_row = 4
        col_grand_totals = [0.0] * len(periods)
        grand_total = 0.0
        for i, (_, row) in enumerate(pivot.iterrows()):
            bg = S.ALT_BG if i % 2 == 1 else S.EVEN_BG
            self._sc(ws, cur_row, 1, row["DATABASE"], bg=bg, halign="left",
                     border=Border(bottom=S.THIN_G))
            self._sc(ws, cur_row, 2, row["CUST_NAME"], bg=bg, halign="left",
                     border=Border(bottom=S.THIN_G))
            for ci, col_key in enumerate(info_cols):
                val = row[col_key]
                if col_key in NUMERIC_INFO_COLS:
                    val = float(val) if pd.notna(val) else None
                    self._sc(ws, cur_row, 3 + ci, val, bg=bg, fmt="#,##0.00", halign="right",
                             border=Border(bottom=S.THIN_G))
                else:
                    self._sc(ws, cur_row, 3 + ci, val, bg=bg, halign="left",
                             border=Border(bottom=S.THIN_G))
            row_total = float(row["TOTAL"])
            self._sc(ws, cur_row, total_col, row_total, bold=True, bg=bg, fmt=ZERO_DASH_USD,
                     border=Border(bottom=S.THIN_G, right=S.THIN))
            for pi, period in enumerate(periods):
                val = float(row[period])
                self._sc(ws, cur_row, month_col_start + pi, val, bg=bg, fmt=ZERO_DASH_USD,
                         border=Border(bottom=S.THIN_G))
                col_grand_totals[pi] += val
            grand_total += row_total
            ws.row_dimensions[cur_row].height = 15
            cur_row += 1

        # Grand total row
        for ci in range(1, N + 1):
            c = ws.cell(row=cur_row, column=ci)
            c.fill   = S.fill(S.GRAND_BG)
            c.font   = S.font(bold=True, color=S.GRAND_FG)
            c.border = Border(top=S.OUTER, bottom=S.OUTER)
        ws.cell(row=cur_row, column=1, value="GRAND TOTAL").alignment = S.align("left")
        self._sc(ws, cur_row, total_col, grand_total, bold=True,
                 fg=S.GRAND_FG, bg=S.GRAND_BG, fmt=ZERO_DASH_USD)
        for pi, total in enumerate(col_grand_totals):
            self._sc(ws, cur_row, month_col_start + pi, total, bold=True,
                     fg=S.GRAND_FG, bg=S.GRAND_BG, fmt=ZERO_DASH_USD)
        ws.row_dimensions[cur_row].height = 16

        S.apply_outer_border(ws, 1, cur_row, 1, N)
        # Freeze Database + Customer + the 4 info columns + Total, plus header row
        ws.freeze_panes = f"{get_column_letter(month_col_start)}4"
        ws.auto_filter.ref = f"A3:{get_column_letter(N)}{cur_row - 1}"
        print(f"  By Customer: {len(pivot)} customers | "
              f"{len(periods)} months | ${grand_total:,.0f}")

    def build(self) -> None:
        self.build_customer_monthly_tab()
        for db in sorted(self.df["DATABASE"].unique()):
            self.build_database_tab(db)


# ═══════════════════════════════════════════════════════════════════════════════
# STANDARD ENTRY POINT (used by report_registry.py / send_reports.py)
# ═══════════════════════════════════════════════════════════════════════════════

def build_attachments() -> list[tuple[str, bytes]]:
    """Loads discount data, builds the workbook in memory, returns [(filename, bytes)]."""
    loader = Loader()
    try:
        df = loader.load()
    finally:
        loader.close()

    wb = Workbook()
    wb.remove(wb.active)
    builder = ReportBuilder(wb, df)
    builder.build()

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return [(f"ar_discounts_report_{_DATE_SUFFIX}.xlsx", buf.getvalue())]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    loader = Loader()
    try:
        df = loader.load()
    finally:
        loader.close()

    wb = Workbook()
    wb.remove(wb.active)
    builder = ReportBuilder(wb, df)
    builder.build()

    wb.save(OUTPUT_FILE)
    print(f"\nSaved -> {OUTPUT_FILE}")
    print(f"Tabs:  {[ws.title for ws in wb.worksheets]}")


if __name__ == "__main__":
    main()