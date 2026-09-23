"""
rpt_ar_discounts.py
====================
Discount tracking report from FCT_GLOBAL_AR_DISCOUNTS (dbt model, built on
top of ARCASH) -- tracks discount amounts applied per database, customer,
and posting period (year/month).

Tabs produced
-------------
  SUMMARY  -- one row per (database, year_period): discount count, total $
  DETAIL   -- flat, sortable/filterable list of every discount transaction
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
    ("Year-Period",      12, "YEAR_PERIOD",    "@",          "center"),
    ("Customer",         28, "CUST_NAME",      "@",          "left"),
    ("Cust Code",        10, "CUST_CODE",      "@",          "center"),
    ("Discount Amt",     14, "DISCOUNT_AMT",   NUM_USD,      "right"),
    ("Ref #",            12, "REF_NUM",        "@",          "center"),
    ("Ref Type",         10, "REF_TYPE",       "@",          "center"),
    ("Payment Method",   16, "PAYMENT_METHOD", "@",          "left"),
    ("Due Date",         13, "DUE_DATE",       "MM/DD/YYYY", "center"),
    ("Payment Date",     13, "PAYMENT_DATE",   "MM/DD/YYYY", "center"),
    ("Journal #",        14, "JOURNAL_NUMBER", "@",          "center"),
    ("Created By",       16, "CREATED_BY",     "@",          "left"),
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
        for col in ["DATABASE", "CUST_NAME", "CUST_CODE", "REF_NUM", "REF_TYPE",
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

    # ── SUMMARY tab: by Database + Year ──────────────────────────────────────

    def build_summary_tab(self) -> None:
        ws = self.wb.create_sheet("SUMMARY", index=0)
        TOTAL_COLS = 4

        self._title_banner(
            ws, TOTAL_COLS,
            f"AR Discount Tracking  |  {TODAY.strftime('%B %d, %Y')}",
            f"{len(self.df):,} discount transactions  |  Source: {MODEL_NAME}",
        )

        headers = ["Database", "Year", "Count", "Discount Amt (USD)"]
        widths  = [14, 10, 10, 18]
        for ci, (hdr, width) in enumerate(zip(headers, widths), start=1):
            c = ws.cell(row=3, column=ci, value=hdr)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=S.THIN_G, right=S.THIN_G,
                                 top=S.OUTER,   bottom=S.OUTER)
            ws.column_dimensions[get_column_letter(ci)].width = width
        ws.row_dimensions[3].height = 18

        grouped = (
            self.df.groupby(["DATABASE", "POSTING_YEAR"])["DISCOUNT_AMT"]
            .agg(["count", "sum"])
            .reset_index()
            .sort_values(["POSTING_YEAR", "DATABASE"], ascending=[False, True])
        )

        cur_row = 4
        grand_count, grand_amt = 0, 0.0
        for i, (_, row) in enumerate(grouped.iterrows()):
            bg = S.ALT_BG if i % 2 == 1 else S.EVEN_BG
            year_val = int(row["POSTING_YEAR"]) if pd.notna(row["POSTING_YEAR"]) else None
            self._sc(ws, cur_row, 1, row["DATABASE"], bg=bg, halign="left",
                     border=Border(bottom=S.THIN_G))
            self._sc(ws, cur_row, 2, year_val, bg=bg, fmt="0", halign="center",
                     border=Border(bottom=S.THIN_G))
            self._sc(ws, cur_row, 3, int(row["count"]), bg=bg, fmt="#,##0",
                     halign="center", border=Border(bottom=S.THIN_G))
            self._sc(ws, cur_row, 4, float(row["sum"]), bg=bg, fmt=NUM_USD,
                     border=Border(bottom=S.THIN_G))
            grand_count += int(row["count"])
            grand_amt   += float(row["sum"])
            ws.row_dimensions[cur_row].height = 15
            cur_row += 1

        self._sc(ws, cur_row, 1, "Grand Total", bold=True,
                 fg=S.GRAND_FG, bg=S.GRAND_BG, halign="left")
        self._sc(ws, cur_row, 2, "", bold=True, fg=S.GRAND_FG, bg=S.GRAND_BG)
        self._sc(ws, cur_row, 3, grand_count, bold=True,
                 fg=S.GRAND_FG, bg=S.GRAND_BG, fmt="#,##0", halign="center")
        self._sc(ws, cur_row, 4, grand_amt, bold=True,
                 fg=S.GRAND_FG, bg=S.GRAND_BG, fmt=NUM_USD)
        ws.row_dimensions[cur_row].height = 16

        S.apply_outer_border(ws, 1, cur_row, 1, TOTAL_COLS)
        ws.freeze_panes = "A4"
        print(f"  Summary: {len(grouped)} database/year groups | "
              f"{grand_count:,} discounts | ${grand_amt:,.0f}")

    # ── per-database DETAIL tab ──────────────────────────────────────────────

    def build_database_tab(self, db: str) -> None:
        safe = (db[:31] or "UNKNOWN").replace("/", "-").replace("\\", "-")
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

    def build(self) -> None:
        self.build_summary_tab()
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