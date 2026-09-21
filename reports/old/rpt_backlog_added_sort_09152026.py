"""
report.py
=========
Reads from FCT_GLOBAL_BACKLOG (Databricks) and renders the Excel workbook.
One query. Python's only jobs: connect, SELECT *, render.

Requires env vars:
  DATABRICKS_SERVER_HOSTNAME   e.g. adb-1234567890123456.7.azuredatabricks.net
  DATABRICKS_HTTP_PATH         e.g. /sql/1.0/warehouses/abc123def456
  DATABRICKS_TOKEN             a personal access token (or see note below for OAuth)

Tabs produced
-------------
  SUMMARY          — one row per segment + BY PRODUCT DIVISION section
  NEW ORDERS       — raw order rows grouped by DATABASE with subtotals
  ALL CUSTOMERS    — full hierarchy: group → segment → customer → product
  <SEGMENT NAME>   — one tab per segment, same hierarchy without segment sub-rows

Run:  python report.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
from databricks import sql as databricks_sql
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

_DIR        = os.path.dirname(os.path.abspath(__file__))
# Output files defined per-config (SEGMENT_CONFIG / REP_CONFIG) in main section

# Databricks SQL Warehouse connection details.
# HTTP_PATH is the "HTTP Path" shown on the warehouse's Connection Details tab,
# e.g. "/sql/1.0/warehouses/xxxxxxxxxxxxxxxx"
DBX_SERVER_HOSTNAME = os.environ["DATABRICKS_SERVER_HOSTNAME"]
DBX_HTTP_PATH       = os.environ["DATABRICKS_HTTP_PATH"]
DBX_ACCESS_TOKEN    = os.environ["DATABRICKS_TOKEN"]

# Catalog / schema that FCT_GLOBAL_BACKLOG lives in (Unity Catalog three-level
# namespace: catalog.schema.table). Adjust to match your workspace.
DBX_CATALOG = "dev"
DBX_SCHEMA  = "gold_sales"

TODAY       = date.today()
CY          = TODAY.year
PY          = CY - 1
CUR_MONTH   = TODAY.month
CUR_QUARTER  = (CUR_MONTH - 1) // 3 + 1

# Fraction of the current year remaining as of today
_YEAR_END    = date(CY, 12, 31)
_TOTAL_DAYS  = (_YEAR_END - date(CY, 1, 1)).days + 1
_DAYS_LEFT   = (_YEAR_END - TODAY).days + 1
YR_PCT_LEFT  = _DAYS_LEFT / _TOTAL_DAYS

# Trend year labels — must match TREND_YR_4..TREND_YR_0 columns in the table
# YR_4 = CY-4 (oldest), YR_0 = CY (most recent)
TREND_YEARS = [CY - 4, CY - 3, CY - 2, CY - 1, CY]
TREND_COLS  = ["TREND_YR_4", "TREND_YR_3", "TREND_YR_2", "TREND_YR_1", "TREND_YR_0"]

DATA_PERIODS = ["Current Month", "YTD", "Current Qtr", "Next Month", "Whole Year"]

# Maps period name → column suffix in FCT_GLOBAL_BACKLOG
PERIOD_COL: dict[str, str] = {
    "Current Month": "CUR_MONTH",
    "YTD":           "YTD",
    "Current Qtr":   "CUR_QTR",
    "Next Month":    "NEXT_MONTH",
    "Whole Year":    "WHOLE_YEAR",
}

# (header label, number format, column prefix)
DATA_SUBCOLS: list[tuple[str, str, str]] = [
    (f"Actual\n{CY}", "#,##0;-#,##0;\"-\"", "CY"),
    (f"Budget\n{CY}", "#,##0;-#,##0;\"-\"", "BGT"),
    (f"Actual\n{PY}", "#,##0;-#,##0;\"-\"", "PY"),
]
VAR_SUBCOLS: list[tuple[str, str]] = [
    ("Month",   "Current Month"),
    ("YTD",     "YTD"),
    ("Quarter", "Current Qtr"),
    ("Next Mo", "Next Month"),
    ("Whole Y", "Whole Year"),
]
PY_VAR_SUBCOLS: list[tuple[str, str]] = [
    ("Month",   "Current Month"),
    ("YTD",     "YTD"),
    ("Quarter", "Current Qtr"),
    ("Next Mo", "Next Month"),
    ("Whole Y", "Whole Year"),
]

ORDERS_COLS: list[tuple[str, int, str, str, str]] = [
    # (header, col_width, source_key, number_format, halign)
    ("Order #",          10, "ORDER_NUM",    "@",          "center"),
    ("Order Date",       13, "ORDER_DATE",   "MM/DD/YYYY", "center"),
    ("Ship Date",        13, "SHIP_DATE",    "MM/DD/YYYY", "center"),
    ("Sales Rep",        16, "SALES_REP",    "@",          "left"),
    ("Cust Code",        10, "CUST_CODE",    "@",          "center"),
    ("Customer",         28, "CUST_NAME",    "@",          "left"),
    ("Product Code",     13, "PRODUCT_CODE", "@",          "center"),
    ("Product",          30, "PRODUCT_NAME", "@",          "left"),
    ("FOB Remark",       22, "FOB_REMARK",   "@",          "left"),
    ("Revenue (in USD)", 16, "REVENUE",      "#,##0.00",   "right"),
    ("Qty (kg)",         13, "QTY_IN_KG",    "#,##0.##",   "right"),
]

NUM_K   = "#,##0;-#,##0;\"-\""
NUM_VAR = "+#,##0;-#,##0;\"-\""

# Type alias
ValDict = dict[str, float]


# ── Report configuration ─────────────────────────────────────────────────────

@dataclass
class ReportConfig:
    """
    Controls which dimension drives the outer pivot of the report.

    pivot_col    : column in FCT_GLOBAL_BACKLOG that defines the top-level
                   grouping — 'REPORTING_SEGMENT' or 'SALES_REP'.
    show_rep_col : True  → col B = Sales Rep, data starts col 3 (segment mode).
                   False → no Sales Rep col, data starts col 2 (rep mode).
    col1_label   : header label for column A in the summary tab.
    output_file  : path to the Excel output file.
    """
    pivot_col:    str
    show_rep_col: bool
    col1_label:   str
    output_file:  str


# ═══════════════════════════════════════════════════════════════════════════════
# ROW → ValDict HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def row_to_vals(row: pd.Series) -> tuple[ValDict, ValDict, ValDict]:
    """Extract (cy_v, bt_v, py_v) dicts from one FCT_GLOBAL_BACKLOG row."""
    cy_v: ValDict = {}
    bt_v: ValDict = {}
    py_v: ValDict = {}
    for period, suffix in PERIOD_COL.items():
        cy_v[period] = float(row.get(f"CY_{suffix}",  0) or 0)
        bt_v[period] = float(row.get(f"BGT_{suffix}", 0) or 0)
        py_v[period] = float(row.get(f"PY_{suffix}",  0) or 0)
    for col, yr in zip(TREND_COLS, TREND_YEARS):
        v = row.get(col)
        cy_v[("trend", yr)] = float(v) if (v is not None and not pd.isna(v)) else None
    return cy_v, bt_v, py_v


def sum_group(rows: pd.DataFrame) -> tuple[ValDict, ValDict, ValDict]:
    """Sum a slice of the DataFrame into (cy_v, bt_v, py_v) dicts."""
    cy_v: ValDict = {}
    bt_v: ValDict = {}
    py_v: ValDict = {}
    for period, suffix in PERIOD_COL.items():
        cy_v[period] = float(rows[f"CY_{suffix}"].sum())
        bt_v[period] = float(rows[f"BGT_{suffix}"].sum())
        py_v[period] = float(rows[f"PY_{suffix}"].sum())
    for col, yr in zip(TREND_COLS, TREND_YEARS):
        total = rows[col].dropna().sum()
        cy_v[("trend", yr)] = float(total) if total else None
    return cy_v, bt_v, py_v


# ═══════════════════════════════════════════════════════════════════════════════
# STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════════

class StyleSheet:
    # Softer slate-blue banner instead of saturated navy — still reads as
    # "header," without the heavy corporate-blue weight.
    TITLE_BG      = "34495E";  TITLE_FG      = "FFFFFF"
    GRP_BG        = "5B84B1";  GRP_FG        = "FFFFFF"
    # Budget/PY variance section headers: muted sage + warm taupe instead of
    # saturated green/orange, so the three header bands read as a coordinated
    # family rather than three competing colors.
    VAR_GRP_BG    = "6E8B6E";  VAR_GRP_FG    = "FFFFFF"
    PY_VAR_GRP_BG = "9C7A54";  PY_VAR_GRP_FG = "FFFFFF"
    COL_BG        = "DCE6F1";  COL_FG        = "000000"
    GRAND_BG      = "34495E";  GRAND_FG      = "FFFFFF"
    CUST_BG       = "FFFFFF";  CUST_FG       = "000000"
    ALT_BG        = "F7F9FC"
    VAR_NEG_BG    = "FBE9E7";  VAR_POS_BG    = "E9F5EC"
    TREND_HDR_BG  = "6C7A89";  TREND_SUB_BG  = "8B98A5"
    GRP_EVEN      = "FFFFFF";  GRP_ODD       = "F7F9FC"
    CUST_ROW      = "F3F7FB";  PROD_ROW      = "F6F3FA"
    NO_MATCH_BG   = "FFF3CD"

    SEP       = Side(style="thin",   color="8FA3BF")
    OUTER     = Side(style="medium", color="6C7A89")
    THIN      = Side(style="thin",   color="B0BAC5")
    THIN_GREY = Side(style="thin",   color="E1E5EA")

    @staticmethod
    def fill(hex_color: str) -> PatternFill:
        return PatternFill("solid", fgColor=hex_color)

    @staticmethod
    def font(bold: bool = False, color: str = "000000",
             size: int = 9, italic: bool = False) -> Font:
        return Font(name="Arial", bold=bold, color=color, size=size, italic=italic)

    @staticmethod
    def align(h: str = "right", v: str = "center", wrap: bool = False) -> Alignment:
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    @classmethod
    def right_sep(cls) -> Border:
        return Border(right=cls.SEP)

    @classmethod
    def var_fill(cls, value: float, row_bg: str,
                 is_grand: bool) -> PatternFill:
        if is_grand:  return cls.fill(cls.GRAND_BG)
        if value < 0: return cls.fill(cls.VAR_NEG_BG)
        if value > 0: return cls.fill(cls.VAR_POS_BG)
        return cls.fill(row_bg)

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


S = StyleSheet


# ═══════════════════════════════════════════════════════════════════════════════
# COLUMN LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ColumnLayout:
    """
    Column index arithmetic for one tab type.
    data_start=2  → Summary tabs (no Sales Rep column, label in col A only).
    data_start=3  → Detail tabs  (col A = label, col B = Sales Rep).
    """
    data_start: int

    n_data_subcols:   int = field(init=False)
    n_var_subcols:    int = field(init=False)
    n_py_var_subcols: int = field(init=False)
    n_trend:          int = field(init=False)
    var_start:        int = field(init=False)
    py_var_start:     int = field(init=False)
    trend_start:      int = field(init=False)
    trend_end:        int = field(init=False)
    total_cols:       int = field(init=False)

    def __post_init__(self) -> None:
        self.n_data_subcols   = len(DATA_SUBCOLS)
        self.n_var_subcols    = len(VAR_SUBCOLS)
        self.n_py_var_subcols = len(PY_VAR_SUBCOLS)
        self.n_trend          = len(TREND_YEARS)
        n_data_cols           = len(DATA_PERIODS) * self.n_data_subcols
        self.var_start        = self.data_start   + n_data_cols
        self.py_var_start     = self.var_start    + self.n_var_subcols
        self.trend_start      = self.py_var_start + self.n_py_var_subcols
        self.trend_end        = self.trend_start  + self.n_trend - 1
        self.pct_col          = self.trend_end    + 1   # % budget remaining
        self.total_cols       = self.pct_col

    def data_col(self, pi: int, si: int) -> int:
        return self.data_start + pi * self.n_data_subcols + si

    def var_col(self,    j: int) -> int: return self.var_start    + j
    def py_var_col(self, j: int) -> int: return self.py_var_start + j
    def trend_col(self, ti: int) -> int: return self.trend_start  + ti

    @property
    def sep_cols(self) -> set[int]:
        cols = {1}
        if self.data_start > 2:
            cols.add(2)
        for i in range(len(DATA_PERIODS)):
            cols.add(self.data_col(i, self.n_data_subcols - 1))
        cols.add(self.var_start    + self.n_var_subcols    - 1)
        cols.add(self.py_var_start + self.n_py_var_subcols - 1)
        cols.add(self.trend_end)
        cols.add(self.pct_col)
        return cols


SUMMARY_LAYOUT = ColumnLayout(data_start=2)
# Detail layout is config-dependent — see ReportBuilder._detail_layout()


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET WRITER
# ═══════════════════════════════════════════════════════════════════════════════

class SheetWriter:
    """Low-level cell / row / header writers bound to one worksheet."""

    def __init__(self, ws: Worksheet, layout: ColumnLayout) -> None:
        self.ws     = ws
        self.layout = layout

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _sc(self, row: int, col: int, value: Any = None, *,
            bold: bool = False, fg: str = "000000",
            bg: str | PatternFill = "FFFFFF",
            fmt: str | None = None, halign: str = "right",
            border=None, italic: bool = False):
        c = self.ws.cell(row=row, column=col, value=value)
        c.font      = S.font(bold=bold, color=fg, italic=italic)
        c.fill      = bg if isinstance(bg, PatternFill) else S.fill(bg)
        c.alignment = S.align(halign)
        if fmt    is not None: c.number_format = fmt
        if border is not None: c.border        = border
        return c

    def _merged_header(self, row: int, sc: int, ec: int, text: str,
                       fg: str, bg: str, border=None) -> None:
        self.ws.merge_cells(start_row=row, start_column=sc,
                            end_row=row,   end_column=ec)
        for col in range(sc, ec + 1):
            self.ws.cell(row=row, column=col).fill = S.fill(bg)
        self._sc(row, sc, text, bold=True, fg=fg, bg=bg, halign="center")
        if border:
            self.ws.cell(row=row, column=ec).border = border

    # ── Data row ─────────────────────────────────────────────────────────────

    def write_data_row(self, row: int, label: str, sales_rep: str,
                       cy_v: ValDict, bt_v: ValDict, py_v: ValDict,
                       is_grand: bool = False, indent: int = 0,
                       bg: str | None = None) -> None:
        L  = self.layout
        bg = bg or (S.GRAND_BG if is_grand else S.GRP_EVEN)
        fg = S.GRAND_FG if is_grand else S.CUST_FG
        b  = is_grand

        lbl_text = ("  " * indent + label) if indent else label
        self._sc(row, 1, lbl_text, bold=b, fg=fg, bg=bg,
                 halign="left", border=S.right_sep())
        if L.data_start > 2:
            self._sc(row, 2, "" if is_grand else sales_rep,
                     italic=True, fg=fg, bg=bg,
                     halign="left", border=S.right_sep())

        # Data columns: CY actual / Budget / PY actual × 5 periods
        pbg = S.GRAND_BG if is_grand else bg
        for i, period in enumerate(DATA_PERIODS):
            vm = {
                "CY":  cy_v.get(period, 0) / 1000,
                "BGT": bt_v.get(period, 0) / 1000,
                "PY":  py_v.get(period, 0) / 1000,
            }
            for j, (_, fmt, prefix) in enumerate(DATA_SUBCOLS):
                self._sc(row, L.data_col(i, j), vm[prefix],
                         bold=b, fg=fg, bg=pbg, fmt=fmt,
                         border=S.right_sep() if j == L.n_data_subcols - 1
                         else None)

        # Budget variance columns (CY vs Budget)
        for j, (_, period) in enumerate(VAR_SUBCOLS):
            v = (cy_v.get(period, 0) - bt_v.get(period, 0)) / 1000
            self._sc(row, L.var_col(j), v, bold=b, fg=fg, fmt=NUM_VAR,
                     bg=S.var_fill(v, bg, is_grand),
                     border=S.right_sep() if j == L.n_var_subcols - 1
                     else None)

        # Prior-year variance columns (CY vs PY)
        for j, (_, period) in enumerate(PY_VAR_SUBCOLS):
            v = (cy_v.get(period, 0) - py_v.get(period, 0)) / 1000
            self._sc(row, L.py_var_col(j), v, bold=b, fg=fg, fmt=NUM_VAR,
                     bg=S.var_fill(v, bg, is_grand),
                     border=S.right_sep() if j == L.n_py_var_subcols - 1
                     else None)

        # Trend columns
        for ti, yr in enumerate(TREND_YEARS):
            val = cy_v.get(("trend", yr))
            self._sc(row, L.trend_col(ti),
                     round(val / 1000, 1) if val is not None else None,
                     bold=b, fg=fg,
                     bg=S.GRAND_BG if is_grand else bg,
                     fmt=NUM_K,
                     border=S.right_sep() if ti == L.n_trend - 1 else Border())

        # % Budget Achieved = CY Whole Year / Budget Whole Year
        cy_wy  = cy_v.get("Whole Year", 0)
        bgt_wy = bt_v.get("Whole Year", 0)
        if bgt_wy and bgt_wy != 0:
            pct = (bgt_wy - cy_wy) / bgt_wy  # % remaining; negative = over budget (good)
        else:
            pct = None
        # Colour: green = over budget (negative remaining = good)
        #         plain = under budget with some remaining
        #         red   = no budget set (None)
        pct_bg = (S.GRAND_BG  if is_grand else
                  S.VAR_POS_BG if (pct is not None and pct <= 0) else
                  bg)
        pct_fg = S.GRAND_FG if is_grand else S.CUST_FG
        self._sc(row, L.pct_col, pct,
                 bold=b, fg=pct_fg, bg=pct_bg,
                 fmt="0%", halign="center",
                 border=S.right_sep())


    # ── Headers ───────────────────────────────────────────────────────────────

    def write_headers(self, title: str, subtitle: str,
                      col1_label: str = "Segment") -> None:
        ws, L = self.ws, self.layout

        # Row 1: title (bold, large, centred)
        self._merged_header(1, 1, L.total_cols, title, S.TITLE_FG, S.TITLE_BG)
        ws.cell(row=1, column=1).font      = S.font(bold=True, color=S.TITLE_FG, size=11)
        ws.cell(row=1, column=1).alignment = S.align("center")
        # Row 2: subtitle — merged across full width, centred, lighter style
        self._merged_header(2, 1, L.total_cols, subtitle, S.COL_BG, S.TITLE_BG)
        ws.cell(row=2, column=1).font      = S.font(bold=False, color=S.COL_BG, size=9)
        ws.cell(row=2, column=1).alignment = S.align("center")

        # Row 3: title fill on label cols, then period group headers
        for col in range(1, L.data_start):
            ws.cell(row=3, column=col).fill = S.fill(S.TITLE_BG)
        for i, period in enumerate(DATA_PERIODS):
            self._merged_header(
                3, L.data_col(i, 0), L.data_col(i, L.n_data_subcols - 1),
                period, S.GRP_FG, S.GRP_BG, border=S.right_sep(),
            )
        for sc, ec, text, fg, bg in [
            (L.var_start,    L.var_start    + L.n_var_subcols    - 1,
             "Budget Target Variance", S.VAR_GRP_FG,    S.VAR_GRP_BG),
            (L.py_var_start, L.py_var_start + L.n_py_var_subcols - 1,
             "CY vs PY Variance",      S.PY_VAR_GRP_FG, S.PY_VAR_GRP_BG),
            (L.trend_start,  L.trend_end,
             "Whole Year Actuals -- 5 Year Trend", "FFFFFF", S.TREND_HDR_BG),
        ]:
            self._merged_header(3, sc, ec, text, fg, bg, border=S.right_sep())
        # pct col row 3 — show % year remaining as context for budget remain
        c3 = self.ws.cell(row=3, column=L.pct_col,
                          value=f"{YR_PCT_LEFT:.0%} Yr Left")
        c3.font      = S.font(bold=True, color="FFFFFF", size=9)
        c3.fill      = S.fill(S.TREND_HDR_BG)
        c3.alignment = S.align("center")
        c3.border    = S.right_sep()

        # Row 4: column sub-headers
        if L.data_start > 2:
            self._sc(4, 2, "Sales Rep", bold=True, bg=S.COL_BG,
                     halign="left", border=S.right_sep())
        self.write_col_subheaders(4, col1_label)

        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 14
        ws.row_dimensions[3].height = 16
        ws.row_dimensions[4].height = 30

    def write_col_subheaders(self, row: int, col1_label: str) -> None:
        L = self.layout
        self._sc(row, 1, col1_label, bold=True, bg=S.COL_BG,
                 halign="left", border=S.right_sep())

        subcols: list[tuple[int, str, bool]] = []
        for i in range(len(DATA_PERIODS)):
            for j, (lbl, _, _) in enumerate(DATA_SUBCOLS):
                subcols.append((L.data_col(i, j), lbl, j == L.n_data_subcols - 1))
        for j, (lbl, _) in enumerate(VAR_SUBCOLS):
            subcols.append((L.var_col(j),    lbl, j == L.n_var_subcols - 1))
        for j, (lbl, _) in enumerate(PY_VAR_SUBCOLS):
            subcols.append((L.py_var_col(j), lbl, j == L.n_py_var_subcols - 1))
        for col, lbl, is_last in subcols:
            c = self.ws.cell(row=row, column=col, value=lbl)
            c.font      = S.font(bold=True)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            if is_last:
                c.border = S.right_sep()

        for ti, yr in enumerate(TREND_YEARS):
            self._sc(row, L.trend_col(ti), str(yr), bold=True,
                     fg="FFFFFF", bg=S.TREND_SUB_BG, halign="center")
        self.ws.cell(row=row, column=L.trend_end).border = S.right_sep()
        # % Budget Achieved subheader
        c = self.ws.cell(row=row, column=L.pct_col,
                         value="Budget Remain")
        c.font      = S.font(bold=True, color="FFFFFF")
        c.fill      = S.fill(S.TREND_SUB_BG)
        c.alignment = S.align("center", wrap=True)
        c.border    = S.right_sep()

    def write_section_separator(self, row: int) -> None:
        L = self.layout
        for col in range(1, L.total_cols + 1):
            self.ws.cell(row=row, column=col).border = Border(
                bottom=S.OUTER,
                right=S.SEP if col in L.sep_cols else None,
            )

    def set_column_widths(self, label_width: int = 28,
                          rep_width: int = 14) -> None:
        L  = self.layout
        cd = self.ws.column_dimensions
        cd["A"].width = label_width
        if L.data_start > 2:
            cd["B"].width = rep_width
        data_cols = [L.data_col(i, j)
                     for i in range(len(DATA_PERIODS))
                     for j in range(L.n_data_subcols)]
        var_cols  = ([L.var_col(j)    for j in range(L.n_var_subcols)]   +
                     [L.py_var_col(j) for j in range(L.n_py_var_subcols)] +
                     [L.trend_col(ti) for ti in range(L.n_trend)])
        for col in data_cols + var_cols:
            cd[get_column_letter(col)].width = 10
        cd[get_column_letter(L.pct_col)].width = 13


# ═══════════════════════════════════════════════════════════════════════════════
# LOADER
# ═══════════════════════════════════════════════════════════════════════════════

class Loader:
    """Connects to Databricks and runs one SELECT against FCT_GLOBAL_BACKLOG."""

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

    def _query(self, sql: str) -> pd.DataFrame:
        cur = self._conn.cursor()
        cur.execute(sql)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(rows, columns=cols)

    def load_new_orders(self) -> pd.DataFrame:
        print("  Loading FCT_GLOBAL_NEW_ORDERS ...")
        df = self._query("""
            SELECT database, order_num, created_date, fob_remark,
                   sales_rep, cust_code, cust_name, product_code, product_name,
                   order_date, ship_date, revenue, qty_in_kg
            FROM FCT_GLOBAL_NEW_ORDERS
        """)
        print(f"    {len(df):,} rows")
        df["REVENUE"]     = pd.to_numeric(df["REVENUE"],     errors="coerce").fillna(0)
        df["QTY_IN_KG"]   = pd.to_numeric(df["QTY_IN_KG"],   errors="coerce").fillna(0)
        df["ORDER_DATE"]   = pd.to_datetime(df["ORDER_DATE"],   errors="coerce")
        df["SHIP_DATE"]    = pd.to_datetime(df["SHIP_DATE"],    errors="coerce")
        df["CREATED_DATE"] = pd.to_datetime(df["CREATED_DATE"], errors="coerce")
        for col in ["ORDER_NUM","CUST_CODE","CUST_NAME","PRODUCT_CODE",
                    "PRODUCT_NAME","SALES_REP","FOB_REMARK","DATABASE"]:
            df[col] = df[col].astype(str).str.strip()\
                          .replace({"nan":"","None":""}).fillna("")
        df = df.sort_values(["DATABASE", "SHIP_DATE"],
                            ascending=[True, False]).reset_index(drop=True)
        return df

    def load(self) -> pd.DataFrame:
        print("  Loading FCT_GLOBAL_BACKLOG ...")
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM FCT_GLOBAL_BACKLOG")
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        df = pd.DataFrame(rows, columns=cols)
        print(f"    {len(df):,} rows, {len(df.columns)} columns")

        # Numeric coercion for all value columns — defensive in case driver
        # returns Decimal objects from Snowflake
        value_prefixes = ("CY_", "BGT_", "PY_", "TREND_", "GRP_", "CST_", "PRD_")
        for col in df.columns:
            if col.startswith(value_prefixes):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

class ReportBuilder:
    """
    Renders the workbook from a single FCT_GLOBAL_BACKLOG DataFrame.

    The DataFrame is already sorted by the dbt model:
      reporting_segment → grp_cy_whole_year DESC → cst_cy_whole_year DESC
      → prd_cy_whole_year DESC

    Python iterates rows and detects key changes to build the hierarchy.
    No re-sorting or aggregation in memory beyond simple groupby sums.
    """

    def __init__(self, wb: Workbook, df: pd.DataFrame,
                 config: ReportConfig) -> None:
        self.wb     = wb
        self.df     = df
        self.config = config

    def ws_merge_title(self, ws: Worksheet, total_cols: int,
                       title: str, subtitle: str) -> None:
        """Write centred title + subtitle banner for the orders tab."""
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

    def build_new_orders_tab(self, orders_df: pd.DataFrame) -> None:
        """NEW ORDERS tab — raw rows grouped by DATABASE with subtotals."""
        ws  = self._new_sheet("NEW ORDERS", index=1)
        N   = len(ORDERS_COLS)
        thin      = S.THIN
        thin_grey = S.THIN_GREY

        rev_col = next(i+1 for i,(_, _, k,_,_) in enumerate(ORDERS_COLS) if k=="REVENUE")
        qty_col = next(i+1 for i,(_, _, k,_,_) in enumerate(ORDERS_COLS) if k=="QTY_IN_KG")

        self.ws_merge_title(ws, N,
            f"Mafco New Orders  |  {TODAY.strftime('%B %d, %Y')}",
            f"{len(orders_df):,} orders  |  Revenue in USD")

        # Row 3: column headers
        for ci, (hdr, width, _, _, _) in enumerate(ORDERS_COLS, start=1):
            c = ws.cell(row=3, column=ci, value=hdr)
            c.font      = S.font(bold=True, color=S.COL_FG)
            c.fill      = S.fill(S.COL_BG)
            c.alignment = S.align("center", wrap=True)
            c.border    = Border(left=thin, right=thin,
                                 top=S.OUTER, bottom=S.OUTER)
            ws.column_dimensions[get_column_letter(ci)].width = width
        ws.row_dimensions[3].height = 28

        cur_row = 4
        grand_rev = 0.0
        grand_qty = 0.0

        for db, db_rows in orders_df.groupby("DATABASE", sort=True):
            db_rev = float(db_rows["REVENUE"].sum())
            db_qty = float(db_rows["QTY_IN_KG"].sum())
            grand_rev += db_rev
            grand_qty += db_qty

            # DB header row
            ws.merge_cells(start_row=cur_row, start_column=1,
                           end_row=cur_row,   end_column=N)
            c = ws.cell(row=cur_row, column=1, value=db)
            c.font      = S.font(bold=True, color=S.GRP_FG)
            c.fill      = S.fill(S.GRP_BG)
            c.alignment = S.align("left")
            c.border    = Border(top=S.OUTER, bottom=thin)
            ws.row_dimensions[cur_row].height = 15
            cur_row += 1

            # Data rows
            for row_idx, (_, row_data) in enumerate(db_rows.iterrows()):
                bg_hex = S.ALT_BG if row_idx % 2 == 1 else S.CUST_BG
                ws.row_dimensions[cur_row].height = 15
                for ci, (_, _, data_key, num_fmt, halign) in enumerate(ORDERS_COLS, start=1):
                    val = row_data.get(data_key, "")
                    if data_key in ("ORDER_DATE", "SHIP_DATE"):
                        val = val.date() if pd.notna(val) and hasattr(val, "date") else None
                    c = ws.cell(row=cur_row, column=ci, value=val)
                    c.font          = S.font(color="000000")
                    c.fill          = S.fill(bg_hex)
                    c.alignment     = S.align(halign)
                    c.number_format = num_fmt
                    c.border        = Border(left=thin_grey, right=thin_grey,
                                             bottom=thin_grey)
                cur_row += 1

            # DB subtotal row
            for ci in range(1, N+1):
                c = ws.cell(row=cur_row, column=ci)
                c.fill   = S.fill(S.COL_BG)
                c.font   = S.font(bold=True)
                c.border = Border(top=thin, bottom=thin,
                                  left=thin_grey, right=thin_grey)
            ws.cell(row=cur_row, column=1,
                    value=f"  {db} Subtotal").alignment = S.align("left")
            ws.cell(row=cur_row, column=1).font = S.font(bold=True)
            for col_idx, value, fmt in [
                (rev_col, db_rev, "#,##0.00"),
                (qty_col, db_qty, "#,##0.##"),
            ]:
                c = ws.cell(row=cur_row, column=col_idx, value=value)
                c.number_format = fmt
                c.alignment     = S.align("right")
                c.font          = S.font(bold=True)
                c.fill          = S.fill(S.COL_BG)
            ws.row_dimensions[cur_row].height = 15
            cur_row += 1

        # Grand total row
        ws.row_dimensions[cur_row].height = 16
        for ci in range(1, N+1):
            c = ws.cell(row=cur_row, column=ci)
            c.fill   = S.fill(S.GRAND_BG)
            c.font   = S.font(bold=True, color=S.GRAND_FG)
            c.border = Border(top=S.OUTER, bottom=S.OUTER,
                              left=S.SEP,  right=S.SEP)
        ws.cell(row=cur_row, column=1, value="GRAND TOTAL").alignment = S.align("left")
        ws.cell(row=cur_row, column=1).font = S.font(bold=True, color=S.GRAND_FG)
        for col_idx, value, fmt in [
            (rev_col, grand_rev, "#,##0.00"),
            (qty_col, grand_qty, "#,##0.##"),
        ]:
            c = ws.cell(row=cur_row, column=col_idx, value=value)
            c.number_format = fmt
            c.alignment     = S.align("right")
            c.font          = S.font(bold=True, color=S.GRAND_FG)
            c.fill          = S.fill(S.GRAND_BG)

        S.apply_outer_border(ws, 1, cur_row, 1, N)
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:{get_column_letter(N)}3"
        print(f"  New orders tab: {len(orders_df):,} rows | "
              f"Revenue ${grand_rev:,.0f} | Qty {grand_qty:,.0f} kg")

    def _sorted_pivot_values(self) -> list[str]:
        """
        Return the ordered list of pivot dimension values.

        Segment mode : NEW BUSINESS last, then by CY whole-year revenue DESC.
        Rep mode     : NEW BUSINESS last, then alphabetical.
        """
        col = self.config.pivot_col
        vals = self.df[col].unique()

        # Both modes: alphabetical, NEW BUSINESS last
        return sorted(vals, key=lambda v: (v != "TOBACCO", v == "NEW BUSINESS", v))

    def _detail_layout(self) -> ColumnLayout:
        """Detail tabs include col B (Sales Rep) only in segment mode."""
        return ColumnLayout(data_start=3 if self.config.show_rep_col else 2)


    def _new_sheet(self, title: str, index: int | None = None) -> Worksheet:
        kwargs: dict[str, Any] = {"title": title}
        if index is not None:
            kwargs["index"] = index
        return self.wb.create_sheet(**kwargs)

    # ── Summary tab ───────────────────────────────────────────────────────────

    def build_summary_tab(self) -> None:
        ws     = self._new_sheet("SUMMARY", index=0)
        L      = SUMMARY_LAYOUT
        writer = SheetWriter(ws, L)
        writer.write_headers(
            f"Mafco Sales Summary  |  {TODAY.strftime('%B %d, %Y')}",
            "Revenue in thousands of USD",
            col1_label=self.config.col1_label,
        )

        # One row per pivot value, sorted per config rules
        segments = self._sorted_pivot_values()

        grand_cy: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_bt: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_py: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_trend: dict = {yr: 0.0 for yr in TREND_YEARS}

        for row_num, seg in enumerate(segments, start=5):
            bg      = S.ALT_BG if row_num % 2 == 0 else S.CUST_BG
            seg_df  = self.df[self.df[self.config.pivot_col] == seg]
            cy_v, bt_v, py_v = sum_group(seg_df)
            writer.write_data_row(row_num, str(seg), "", cy_v, bt_v, py_v, bg=bg)
            for p in DATA_PERIODS:
                grand_cy[p] += cy_v.get(p, 0)
                grand_bt[p] += bt_v.get(p, 0)
                grand_py[p] += py_v.get(p, 0)
            for yr in TREND_YEARS:
                grand_trend[yr] += cy_v.get(("trend", yr), 0) or 0

        gt_row = len(segments) + 5
        writer.write_section_separator(gt_row - 1)

        for yr in TREND_YEARS:
            grand_cy[("trend", yr)] = grand_trend[yr] or None
        writer.write_data_row(gt_row, "Grand Total", "",
                              grand_cy, grand_bt, grand_py, is_grand=True)

        if self.config.show_rep_col:  # segment mode only
            self._build_division_section(ws, writer, gt_row)

        writer.set_column_widths(label_width=28)
        ws.freeze_panes = "B5"
        S.apply_outer_border(ws, 1, gt_row, 1, L.total_cols)

    def _build_division_section(self, ws: Worksheet, writer: SheetWriter,
                                 gt_row: int) -> None:
        """BY PRODUCT DIVISION section appended below the segment grand total."""
        L = SUMMARY_LAYOUT

        # Divisions sorted: NEW BUSINESS last, then alpha — matches original Python
        divs = sorted(
            self.df["PRODUCT_DIVISION"].unique(),
            key=lambda d: (d == "NEW BUSINESS", d),
        )
        if not divs:
            return

        hdr_row = gt_row + 2
        ws.merge_cells(start_row=hdr_row, start_column=1,
                       end_row=hdr_row,   end_column=L.total_cols)
        c = ws.cell(row=hdr_row, column=1, value="BY PRODUCT DIVISION")
        c.font = S.font(bold=True, color=S.TITLE_FG, size=10)
        c.fill = S.fill(S.TITLE_BG); c.alignment = S.align("left")
        ws.row_dimensions[hdr_row].height = 16

        sub_row = hdr_row + 1
        ws.row_dimensions[sub_row].height = 28
        writer.write_col_subheaders(sub_row, "Product Division")

        grand_cy: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_bt: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_py: ValDict = {p: 0.0 for p in DATA_PERIODS}
        grand_trend: dict = {yr: 0.0 for yr in TREND_YEARS}
        cur_row = sub_row + 1

        for di, div in enumerate(divs):
            bg     = S.ALT_BG if di % 2 == 0 else S.CUST_BG
            div_df = self.df[self.df["PRODUCT_DIVISION"] == div]
            cy_v, bt_v, py_v = sum_group(div_df)
            writer.write_data_row(cur_row, div, "", cy_v, bt_v, py_v, bg=bg)
            for p in DATA_PERIODS:
                grand_cy[p] += cy_v.get(p, 0)
                grand_bt[p] += bt_v.get(p, 0)
                grand_py[p] += py_v.get(p, 0)
            for yr in TREND_YEARS:
                grand_trend[yr] += cy_v.get(("trend", yr), 0) or 0
            cur_row += 1

        writer.write_section_separator(cur_row - 1)
        for yr in TREND_YEARS:
            grand_cy[("trend", yr)] = grand_trend[yr] or None
        writer.write_data_row(cur_row, "Grand Total", "",
                              grand_cy, grand_bt, grand_py, is_grand=True)
        S.apply_outer_border(ws, hdr_row, cur_row, 1, L.total_cols)

    # ── Detail tabs (ALL CUSTOMERS + per-segment) ─────────────────────────────

    def build_all_customers_tab(self) -> None:
        ws = self._new_sheet("ALL CUSTOMERS")
        self._render_detail_tab(
            ws       = ws,
            df       = self.df,
            title    = f"Mafco Sales Report  |  All Customers  |  {TODAY.strftime('%B %d, %Y')}",
            is_all   = True,
        )

    def build_pivot_tab(self, segment: str) -> None:
        safe = (segment[:31]
                .replace("/",  "-").replace("\\", "-")
                .replace("*",  "").replace("?",   "")
                .replace("[",  "").replace("]",   "")
                .replace(":",  "").upper())
        ws     = self._new_sheet(safe)
        seg_df = self.df[self.df[self.config.pivot_col] == segment]
        self._render_detail_tab(
            ws       = ws,
            df       = seg_df,
            title    = f"Mafco Sales Report  |  {segment}  |  {TODAY.strftime('%B %d, %Y')}",
            is_all   = False,
        )

    def _render_detail_tab(self, ws: Worksheet, df: pd.DataFrame,
                           title: str, is_all: bool) -> None:
        """
        Shared renderer for ALL CUSTOMERS and per-segment tabs.

        Hierarchy
        ---------
        ALL CUSTOMERS:  Grand Total
                        └── Group  (sorted by grp_cy_whole_year DESC)
                            └── Segment sub-row  (outline 1, hidden)
                                └── Customer     (outline 2, hidden)
                                    └── Product  (outline 3, hidden)

        SEGMENT:        Grand Total
                        └── Segment label bar
                            └── Group  (sorted by grp_cy_whole_year DESC)
                                └── Customer  (outline 1, hidden)
                                    └── Product (outline 2, hidden)
        """
        L      = self._detail_layout()
        writer = SheetWriter(ws, L)
        writer.write_headers(title, "Revenue in thousands of USD",
                             col1_label="Customer Group")

        # Grand total across all rows passed in
        grand_cy, grand_bt, grand_py = sum_group(df)
        cur = 5
        writer.write_data_row(cur, "Grand Total", "",
                              grand_cy, grand_bt, grand_py, is_grand=True)
        cur += 1

        if not is_all:
            # Segment label bar — full-width blue row
            seg_name = str(df[self.config.pivot_col].iloc[0]) if not df.empty else ""
            ws.cell(row=cur, column=1, value=seg_name.upper()).font = \
                S.font(bold=True, color=S.GRP_FG)
            ws.cell(row=cur, column=1).fill      = S.fill(S.GRP_BG)
            ws.cell(row=cur, column=1).alignment = S.align("left")
            for col in range(2, L.total_cols + 1):
                ws.cell(row=cur, column=col).fill = S.fill(S.GRP_BG)
            cur += 1

        # Sort groups by CY whole-year revenue DESC, NEW BUSINESS last
        grp_order = (
            df.groupby("CUST_GROUP")["CY_WHOLE_YEAR"]
            .sum()
            .reset_index()
            .assign(_nb=lambda x: x["CUST_GROUP"] == "NEW BUSINESS")
            .sort_values(["_nb", "CY_WHOLE_YEAR"], ascending=[True, False])
            ["CUST_GROUP"].tolist()
        )
        for grp_idx, grp_key in enumerate(grp_order):
            grp_rows = df[df["CUST_GROUP"] == grp_key]
            grp_bg   = S.GRP_EVEN if grp_idx % 2 == 0 else S.GRP_ODD

            grp_cy, grp_bt, grp_py = sum_group(grp_rows)

            # Rep = sales_rep of the customer with highest cst_cy_whole_year
            top = grp_rows.sort_values("CST_CY_WHOLE_YEAR", ascending=False).iloc[0]
            grp_rep = str(top["SALES_REP"])

            writer.write_data_row(cur, grp_key, grp_rep,
                                  grp_cy, grp_bt, grp_py,
                                  indent=1, bg=grp_bg)
            cur += 1

            if is_all:
                # Segment sub-rows within this group (collapsed)
                seg_order = (
                    grp_rows.groupby("REPORTING_SEGMENT")["CY_WHOLE_YEAR"]
                    .sum().sort_values(ascending=False).index.tolist()
                )
                for seg in seg_order:
                    seg_rows = grp_rows[grp_rows["REPORTING_SEGMENT"] == seg]
                    seg_cy, seg_bt, seg_py = sum_group(seg_rows)
                    writer.write_data_row(cur, f"  {seg}", "",
                                         seg_cy, seg_bt, seg_py,
                                         indent=0, bg=S.GRP_BG)
                    for col in range(1, L.total_cols + 1):
                        c = ws.cell(row=cur, column=col)
                        c.fill = S.fill(S.GRP_BG)
                        c.font = Font(name="Arial", bold=True,
                                      color=S.GRP_FG, size=9)
                    ws.cell(row=cur, column=1).alignment = S.align("left")
                    ws.row_dimensions[cur].outline_level = 1
                    ws.row_dimensions[cur].hidden = True
                    cur += 1

                    cur = self._write_customers(
                        writer, ws, seg_rows, cur,
                        cust_outline=2, prod_outline=3,
                    )
            else:
                cur = self._write_customers(
                    writer, ws, grp_rows, cur,
                    cust_outline=1, prod_outline=2,
                )

        writer.write_section_separator(cur - 1)
        writer.set_column_widths(label_width=32 if is_all else 30)
        ws.freeze_panes = "C6" if self.config.show_rep_col else "B6"
        ws.sheet_properties.outlinePr.summaryBelow = False
        S.apply_outer_border(ws, 1, cur, 1, L.total_cols)

    def _write_customers(self, writer: SheetWriter, ws: Worksheet,
                         rows: pd.DataFrame, cur: int,
                         cust_outline: int, prod_outline: int) -> int:
        """Write customer rows and their product sub-rows. Returns next row index."""
        L = writer.layout
        for (db, cust_code), cust_rows in rows.groupby(
                ["DATABASE", "CUST_CODE"], sort=False):
            cust_name = str(cust_rows["CUST_NAME"].iloc[0])
            sales_rep = str(cust_rows["SALES_REP"].iloc[0])
            cust_cy, cust_bt, cust_py = sum_group(cust_rows)
            writer.write_data_row(cur, cust_name, sales_rep,
                                  cust_cy, cust_bt, cust_py,
                                  indent=2, bg=S.CUST_ROW)
            ws.row_dimensions[cur].outline_level = cust_outline
            ws.row_dimensions[cur].hidden = True
            cur += 1

            # Products already sorted by prd_cy_whole_year DESC from dbt
            prod_rows = cust_rows.sort_values("PRD_CY_WHOLE_YEAR", ascending=False)
            for _, prod_row in prod_rows.iterrows():
                is_no_match = bool(prod_row.get("IS_NO_SALES_MATCH", False))
                row_bg      = S.NO_MATCH_BG if is_no_match else S.PROD_ROW
                cy_v, bt_v, py_v = row_to_vals(prod_row)
                writer.write_data_row(
                    cur, str(prod_row["PROD_LABEL"]), "",
                    cy_v, bt_v, py_v,
                    indent=3, bg=row_bg,
                )
                ws.row_dimensions[cur].outline_level = prod_outline
                ws.row_dimensions[cur].hidden = True
                cur += 1

        return cur


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

# ── Report configurations ────────────────────────────────────────────────────

# Date suffix appended to output filenames — e.g. 04252026
_DATE_SUFFIX = TODAY.strftime("%m%d%Y")

SEGMENT_CONFIG = ReportConfig(
    pivot_col    = "REPORTING_SEGMENT",
    show_rep_col = True,
    col1_label   = "Segment",
    output_file  = os.path.join(_DIR, f"sales_report_by_product_segment_{_DATE_SUFFIX}.xlsx"),
)

REP_CONFIG = ReportConfig(
    pivot_col    = "SALES_REP",
    show_rep_col = False,
    col1_label   = "Sales Rep",
    output_file  = os.path.join(_DIR, f"sales_report_by_sales_rep_{_DATE_SUFFIX}.xlsx"),
)


def build_report(df: pd.DataFrame, orders_df: pd.DataFrame,
                 config: ReportConfig) -> None:
    """Build one Excel workbook from df using the given config."""
    wb      = Workbook()
    wb.remove(wb.active)
    builder = ReportBuilder(wb, df, config)
    pivot_values = builder._sorted_pivot_values()

    builder.build_summary_tab()
    builder.build_new_orders_tab(orders_df)   # after SUMMARY, before ALL CUSTOMERS
    builder.build_all_customers_tab()
    for val in pivot_values:
        builder.build_pivot_tab(val)

    wb.save(config.output_file)
    print(f"\nSaved → {config.output_file}")
    print(f"Tabs:  {[ws.title for ws in wb.worksheets]}")


def main() -> None:
    loader = Loader()
    try:
        df        = loader.load()
        orders_df = loader.load_new_orders()
    finally:
        loader.close()

    print("\nBuilding segment report...")
    build_report(df, orders_df, SEGMENT_CONFIG)

    print("\nBuilding sales rep report...")
    build_report(df, orders_df, REP_CONFIG)

    print(f"\nCY={CY}  PY={PY}  Month={CUR_MONTH}  Q{CUR_QUARTER}")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDARD ENTRY POINT (used by report_registry.py / send_reports.py)
# ═══════════════════════════════════════════════════════════════════════════════

def build_attachments() -> list[tuple[str, bytes]]:
    """Loads data ONCE, builds BOTH the segment and sales-rep workbooks from
    it, returns both as attachments -- matches the original report_emailer.py
    design (one 'Executive team' email with two attachments), and avoids
    re-querying FCT_GLOBAL_BACKLOG twice."""
    import copy
    import io

    loader = Loader()
    try:
        df        = loader.load()
        orders_df = loader.load_new_orders()
    finally:
        loader.close()

    attachments: list[tuple[str, bytes]] = []
    for config_template, filename in [
        (SEGMENT_CONFIG, f"sales_report_by_product_segment_{_DATE_SUFFIX}.xlsx"),
        (REP_CONFIG, f"sales_report_by_sales_rep_{_DATE_SUFFIX}.xlsx"),
    ]:
        buf = io.BytesIO()
        config = copy.copy(config_template)
        config.output_file = buf
        build_report(df, orders_df, config)
        buf.seek(0)
        attachments.append((filename, buf.getvalue()))

    return attachments


if __name__ == "__main__":
    main()