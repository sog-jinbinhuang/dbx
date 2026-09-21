"""
rpt_open_orders.py
===================
Open Order report from FCT_GLOBAL_SALES_ORDERS_3, filtered to rows where
SALES_OR_ORDER = 'ORDER' -- i.e. orders that haven't shipped/invoiced yet,
as opposed to 'SALES' rows which represent completed transactions.

Single flat, sortable/filterable tab (not split by database) -- built for
planning use: sorted by Ship Date ascending by default (most urgent first),
with Excel auto-filter enabled on every column so it can be re-sorted or
filtered by Database, Customer, Product, date range, etc. without switching
tabs.
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
DBX_SCHEMA          = "gold_sales"

SOURCE_TABLE = "FCT_GLOBAL_SALES_ORDERS_3"

TODAY        = date.today()
_DATE_SUFFIX = TODAY.strftime("%m%d%Y")
OUTPUT_FILE  = os.path.join(_DIR, f"open_order_report_{_DATE_SUFFIX}.xlsx")

# One row per order line. Ship Date sourced from INVOICE_DATE (planned/
# expected ship date convention for open orders), Order Date from ORDER_DATE.
DETAIL_COLS: list[tuple[str, int, str, str, str]] = [
    # (header, col_width, source_key, number_format, halign)
    ("Database",         12, "DATABASE",       "@",          "left"),
    ("Order #",          10, "ORDER_NUM",      "@",          "center"),
    ("Order Date",       13, "ORDER_DATE",     "MM/DD/YYYY", "center"),
    ("Ship Date",        13, "INVOICE_DATE",   "MM/DD/YYYY", "center"),
    ("Sales Rep",        16, "SALES_REP",      "@",          "left"),
    ("Cust Code",        10, "CUST_CODE",      "@",          "center"),
    ("Customer",         28, "CUST_NAME",      "@",          "left"),
    ("Product Code",     13, "PRODUCT_CODE",   "@",          "center"),
    ("Product",          30, "PRODUCT_NAME",   "@",          "left"),
    ("Revenue (USD)",    16, "REVENUE",        "#,##0.00",   "right"),
    ("Qty (kg)",         13, "QTY_IN_KG",      "#,##0.##",   "right"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# STYLESHEET -- lighter slate-blue theme, matching the other converted reports
# ═══════════════════════════════════════════════════════════════════════════════

class S:
    TITLE_BG = "34495E"; TITLE_FG = "FFFFFF"
    COL_BG   = "DCE6F1"; COL_FG   = "000000"
    GRAND_BG = "34495E"; GRAND_FG = "FFFFFF"
    ALT_BG   = "F7F9FC"; EVEN_BG  = "FFFFFF"
    # Subtle per-database tint (alternates so adjacent databases are visually
    # distinguishable even while sorted by ship date, not grouped by db)
    DB_TINTS = ["FFFFFF", "F7F9FC", "F3F7FB", "F6F3FA", "FBF9F3"]
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
            http_path       = DBX_HTTP_PATH,
            access_token    = DBX_ACCESS_TOKEN,
            catalog          = DBX_CATALOG,
            schema           = DBX_SCHEMA,
        )
        print("  Connected.")

    def close(self) -> None:
        self._conn.close()
        print("  Databricks connection closed.")

    def load(self) -> pd.DataFrame:
        # SALES_OR_ORDER = 'ORDER' identifies rows that haven't shipped/
        # invoiced yet -- 'SALES' rows are completed transactions, excluded
        # here since this report is specifically the OPEN order backlog.
        query = f"""
            SELECT
                DATABASE, ORDER_NUM, ORDER_DATE, INVOICE_DATE,
                SALES_REP, CUST_NAME, CUST_CODE, PRODUCT_CODE, PRODUCT_NAME,
                REVENUE, QTY_IN_KG
            FROM {SOURCE_TABLE}
            WHERE upper(SALES_OR_ORDER) = 'ORDER'
        """
        print(f"  Loading {SOURCE_TABLE} (open orders only) ...")
        cur = self._conn.cursor()
        cur.execute(query)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()

        df = pd.DataFrame(rows, columns=cols)
        print(f"    {len(df):,} rows returned")

        df["REVENUE"]   = pd.to_numeric(df["REVENUE"],   errors="coerce").fillna(0)
        df["QTY_IN_KG"] = pd.to_numeric(df["QTY_IN_KG"], errors="coerce").fillna(0)
        df["ORDER_DATE"]   = pd.to_datetime(df["ORDER_DATE"],   errors="coerce")
        df["INVOICE_DATE"] = pd.to_datetime(df["INVOICE_DATE"], errors="coerce")
        for col in ["DATABASE", "ORDER_NUM", "SALES_REP", "CUST_NAME",
                    "CUST_CODE", "PRODUCT_CODE", "PRODUCT_NAME"]:
            df[col] = (df[col].astype(str).str.strip()
                       .replace({"nan": "", "None": ""}).fillna(""))

        # Sorted by Ship Date ascending (most urgent to plan first) -- this
        # is the default view; the sheet's auto-filter lets it be re-sorted
        # by any other column directly in Excel for planning purposes.
        df = df.sort_values(
            "INVOICE_DATE", ascending=True, na_position="last"
        ).reset_index(drop=True)
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDER -- single flat, filterable tab
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

    def build(self) -> None:
        ws = self.wb.create_sheet("OPEN ORDERS", index=0)
        N = len(DETAIL_COLS)
        df = self.df

        rev_col = next(i + 1 for i, (_, _, k, _, _) in enumerate(DETAIL_COLS) if k == "REVENUE")
        qty_col = next(i + 1 for i, (_, _, k, _, _) in enumerate(DETAIL_COLS) if k == "QTY_IN_KG")
        db_col  = next(i + 1 for i, (_, _, k, _, _) in enumerate(DETAIL_COLS) if k == "DATABASE")

        # Title banner
        for row, text, bold, size, color in [
            (1, f"Open Order Report  |  {TODAY.strftime('%B %d, %Y')}", True, 11, S.TITLE_FG),
            (2, f"{len(df):,} open orders  |  Sorted by Ship Date  |  Source: {SOURCE_TABLE}", False, 9, S.COL_BG),
        ]:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=N)
            c = ws.cell(row=row, column=1, value=text)
            c.font = S.font(bold=bold, color=color, size=size)
            c.fill = S.fill(S.TITLE_BG)
            c.alignment = S.align("center")
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 14

        # Column headers
        for ci, (hdr, width, _, _, _) in enumerate(DETAIL_COLS, start=1):
            c = ws.cell(row=3, column=ci, value=hdr)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=S.THIN_G, right=S.THIN_G,
                                 top=S.OUTER,   bottom=S.OUTER)
            ws.column_dimensions[get_column_letter(ci)].width = width
        ws.row_dimensions[3].height = 20

        # Data rows -- flat, one per order line, tinted per-database (cycling
        # through S.DB_TINTS by database name) so adjacent databases are
        # visually distinguishable even though the sheet is sorted by ship
        # date rather than grouped by database.
        databases_seen = sorted(df["DATABASE"].unique())
        db_tint_map = {db: S.DB_TINTS[i % len(S.DB_TINTS)] for i, db in enumerate(databases_seen)}

        cur_row = 4
        grand_rev, grand_qty = 0.0, 0.0
        for _, r in df.iterrows():
            bg = db_tint_map.get(r["DATABASE"], S.EVEN_BG)
            ws.row_dimensions[cur_row].height = 15
            for ci, (_, _, key, fmt, halign) in enumerate(DETAIL_COLS, start=1):
                val = r[key]
                if key in ("ORDER_DATE", "INVOICE_DATE"):
                    val = val.date() if pd.notna(val) and hasattr(val, "date") else None
                c = ws.cell(row=cur_row, column=ci, value=val)
                c.font          = S.font(color="000000")
                c.fill          = S.fill(bg)
                c.alignment     = S.align(halign)
                c.number_format = fmt
                c.border        = Border(left=S.THIN_G, right=S.THIN_G, bottom=S.THIN_G)
            grand_rev += float(r["REVENUE"])
            grand_qty += float(r["QTY_IN_KG"])
            cur_row += 1

        # Grand total row
        for ci in range(1, N + 1):
            c = ws.cell(row=cur_row, column=ci)
            c.fill   = S.fill(S.GRAND_BG)
            c.font   = S.font(bold=True, color=S.GRAND_FG)
            c.border = Border(top=S.OUTER, bottom=S.OUTER)
        ws.cell(row=cur_row, column=1, value="GRAND TOTAL").alignment = S.align("left")
        self._sc(ws, cur_row, rev_col, grand_rev, bold=True, fg=S.GRAND_FG, bg=S.GRAND_BG, fmt="#,##0.00")
        self._sc(ws, cur_row, qty_col, grand_qty, bold=True, fg=S.GRAND_FG, bg=S.GRAND_BG, fmt="#,##0.##")
        ws.row_dimensions[cur_row].height = 16

        S.apply_outer_border(ws, 1, cur_row, 1, N)

        # Freeze panes below the header row, and enable Excel's auto-filter
        # on the header row so the sheet can be sorted/filtered by any
        # column (Database, Customer, Ship Date, etc.) directly in Excel
        # for planning -- e.g. "show me only US orders shipping this week."
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:{get_column_letter(N)}{cur_row - 1}"

        print(f"  Open Orders: {len(df):,} rows | {len(databases_seen)} databases | "
              f"${grand_rev:,.0f} revenue")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDARD ENTRY POINT (used by report_registry.py / send_reports.py)
# ═══════════════════════════════════════════════════════════════════════════════

def build_attachments() -> list[tuple[str, bytes]]:
    """Loads open orders, builds the single-tab workbook in memory, returns
    [(filename, bytes)]."""
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

    return [(f"open_order_report_{_DATE_SUFFIX}.xlsx", buf.getvalue())]


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