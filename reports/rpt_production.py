"""
production_report.py
====================
Layout per entity tab:

  VOLUME
  COST OF PRODUCTION
    Direct Material
    Overhead (Variable / Fixed)
    Unit Cost
    Standard Absorption
  VOLUME BY PROCESS

Run:  python production_report.py
"""

from __future__ import annotations

import os
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

_DIR         = os.path.dirname(os.path.abspath(__file__))
TODAY        = date.today()
_DATE_SUFFIX = TODAY.strftime("%m%d%Y")
OUTPUT_FILE  = os.path.join(_DIR, f"production_report_{_DATE_SUFFIX}.xlsx")

# NOTE: FCT_PRODUCTION_VOLUME_COST and FCT_PRODUCTION_OPEX have not been
# confirmed to exist in the new Databricks workspace yet -- this catalog/
# schema is a placeholder assumption (production costs -> finance domain,
# same catalog as the AP/AR/backlog reports). Confirm and update once that
# migration is done.
DBX_SERVER_HOSTNAME = os.environ["DATABRICKS_SERVER_HOSTNAME"]
DBX_HTTP_PATH       = os.environ["DATABRICKS_HTTP_PATH"]
DBX_ACCESS_TOKEN    = os.environ["DATABRICKS_TOKEN"]

DBX_CATALOG = "dev"
DBX_SCHEMA  = "gold_production"

ENTITIES = ["EVD", "US", "CHINA", "WEIFENG", "CHILE"]

CY = TODAY.year
PY = CY - 1

MONTHS = [
    (1,  "Jan"), (2,  "Feb"), (3,  "Mar"),
    (4,  "Apr"), (5,  "May"), (6,  "Jun"),
    (7,  "Jul"), (8,  "Aug"), (9,  "Sep"),
    (10, "Oct"), (11, "Nov"), (12, "Dec"),
]

FMT_VOL  = "#,##0;-#,##0;\"-\""
FMT_COST = "#,##0.00;-#,##0.00;\"-\""
FMT_USD  = "#,##0;-#,##0;\"-\""
FMT_VUSD = "+#,##0;-#,##0;\"-\""
FMT_VVAR = "+#,##0.00;-#,##0.00;\"-\""

BOTTOM_PROCESSES = {"EVD", "RICHMOND", "REMELTS","CHINA"}

CAT_VAR = "Variable O/H Cost"
CAT_FIX = "Fixed O/H Cost"
CAT_DM  = "Direct Material Cost"
CAT_ABS = "Absorption Variance"

ENTITY_VAR_FIX_OH_PROCESS: dict[str, list[str] | None] = {
    "EVD": None, "US": None, "CHINA": None, "WEIFENG": None, "CHILE": None,
}
ENTITY_DM_PROCESS: dict[str, list[str] | None] = {
    "EVD":     ["EVD"],
    "US":      ["RICHMOND", "REMELTS"],
    "CHINA":   None, "WEIFENG": None, "CHILE": None,
}
ENTITY_ABS_PROCESS: dict[str, list[str] | None] = {
    "EVD": None, "US": None, "CHINA": None, "WEIFENG": None, "CHILE": None,
}


# ═══════════════════════════════════════════════════════════════════════════════
# COLUMN LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

D_MO_CY     = 2
D_MO_PY     = 3
D_MO_VAR    = 4
D_SEP1      = 5
D_QTD_CY    = 6
D_QTD_PY    = 7
D_QTD_VAR   = 8
D_SEP2      = 9
D_YTD_CY    = 10
D_YTD_PY    = 11
D_YTD_VAR   = 12
D_SEP3      = 13
D_MON_START = 14
D_N_MONTHS  = 12
D_TOTAL     = D_MON_START + D_N_MONTHS - 1


def d_mon_col(idx: int) -> int:
    return D_MON_START + idx


# ═══════════════════════════════════════════════════════════════════════════════
# STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════════

class S:
    # Lighter slate-blue theme (matches rpt_sales_volume.py) — soft tinted
    # fills instead of near-black blocks, muted accent instead of heavy navy.
    TITLE_BG  = "44546A";  TITLE_FG  = "FFFFFF"
    PERIOD_BG = "6D89AC";  PERIOD_FG = "FFFFFF"
    QTD_BG    = "8FA8C4";  QTD_FG    = "FFFFFF"
    MON_BG    = "8FA8C4";  MON_FG    = "FFFFFF"
    HDR_BG    = "D9E2F3";  HDR_FG    = "44546A"

    SECT_BG   = "44546A";  SECT_FG   = "FFFFFF"
    SUB_BG    = "D9E2F3";  SUB_FG    = "44546A"
    SUBSUB_BG = "FFFFFF";  SUBSUB_FG = "6D89AC"

    ROW_EVEN  = "FFFFFF"
    ROW_ODD   = "F8F9FB"
    ROW_TOTAL = "EDF1F8"
    ROW_PROC  = "F8F9FB"
    ROW_DRILL = "FBFCFE"   # GL account drill-down rows

    DATA_FG   = "44546A"
    MUTED_FG  = "AAB8CC"
    TOTAL_FG  = "44546A"
    ITALIC_FG = "5C7A96"
    DRILL_FG  = "8FA0B3"   # muted — clearly secondary to type row

    VAR_POS_BG = "EAF4EA";  VAR_POS_FG = "2D6A2D"
    VAR_NEG_BG = "FDEEEE";  VAR_NEG_FG = "8B2020"

    HAIR     = Side(style="thin",   color="D9E2F3")
    SEP      = Side(style="medium", color="8FA8C4")
    SEP_QTD  = Side(style="medium", color="8FA8C4")
    SEP_MON  = Side(style="thin",   color="AAB8CC")

    @staticmethod
    def fill(hex_color: str) -> PatternFill:
        return PatternFill("solid", fgColor=hex_color)

    @staticmethod
    def font(bold: bool = False, color: str = "1E2D3D",
             size: int = 9, italic: bool = False) -> Font:
        return Font(name="Calibri", bold=bold, color=color,
                    size=size, italic=italic)

    @staticmethod
    def align(h: str = "right", v: str = "center",
              wrap: bool = False) -> Alignment:
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    @classmethod
    def var_fill_fg(cls, value: float | None,
                    row_bg: str) -> tuple[PatternFill, str]:
        if value is None:
            return cls.fill(row_bg), cls.DATA_FG
        if value < 0:
            return cls.fill(cls.VAR_NEG_BG), cls.VAR_NEG_FG
        if value > 0:
            return cls.fill(cls.VAR_POS_BG), cls.VAR_POS_FG
        return cls.fill(row_bg), cls.DATA_FG

    @classmethod
    def apply_outer_border(cls, ws: Worksheet,
                           r1: int, r2: int,
                           c1: int, c2: int) -> None:
        brd = Side(style="thin", color="8FA3B1")
        for r in range(r1, r2 + 1):
            lc = ws.cell(row=r, column=c1)
            rc = ws.cell(row=r, column=c2)
            lc.border = Border(left=brd,
                               top=lc.border.top,
                               bottom=lc.border.bottom,
                               right=lc.border.right)
            rc.border = Border(right=brd,
                               top=rc.border.top,
                               bottom=rc.border.bottom,
                               left=rc.border.left)


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

    def _query(self, sql: str) -> pd.DataFrame:
        cur = self._conn.cursor()
        cur.execute(sql)
        cols = [d[0].lower() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(rows, columns=cols)

    def load_volume_cost(self) -> pd.DataFrame:
        print("  Loading FCT_PRODUCTION_VOLUME_COST ...")
        df = self._query("SELECT * FROM FCT_PRODUCTION_VOLUME_COST")
        print(f"    {len(df):,} rows")
        num_cols = [c for c in df.columns if any(
            c.startswith(p) for p in ("cy_", "py_", "var_"))]
        for col in num_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ["entity", "absorption_category", "product_code",
                    "product_name", "product_segment",
                    "packaging_code", "prod_pkg_code"]:
            if col in df.columns:
                df[col] = (df[col].astype(str).str.strip()
                           .replace({"nan": "", "None": ""}).fillna(""))
        return df

    def load_opex(self) -> pd.DataFrame:
        print("  Loading FCT_PRODUCTION_OPEX ...")
        df = self._query("SELECT * FROM FCT_PRODUCTION_OPEX")
        print(f"    {len(df):,} rows")
        num_cols = [c for c in df.columns if any(
            c.startswith(p) for p in ("cy_", "py_", "var_"))]
        for col in num_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ["entity", "category", "process", "type",
                    "account_num", "account_en"]:
            if col in df.columns:
                df[col] = (df[col].astype(str).str.strip()
                           .replace({"nan": "", "None": ""}).fillna(""))
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _get(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    return float(v) if v is not None and pd.notna(v) else None

def _sum(df: pd.DataFrame, col: str) -> float | None:
    if col not in df.columns:
        return None
    v = df[col].sum()
    return float(v) if pd.notna(v) else None

def _build_monthly(df: pd.DataFrame, cy_base: str) -> list[float | None]:
    return [_sum(df, f"{cy_base}_m{m:02d}") for m, _ in MONTHS]

def _sum_type_group(df: pd.DataFrame) -> dict:
    num_cols = [c for c in df.columns if any(
        c.startswith(p) for p in ("cy_", "py_", "var_"))]
    s = df[num_cols].sum()
    return {c: (float(s[c]) if pd.notna(s[c]) else None) for c in num_cols}

def _row_from_summed(ts: dict) -> dict:
    return dict(
        mo_cy   = ts.get("cy_cur_month"),
        mo_py   = ts.get("py_cur_month"),
        qtd_cy  = ts.get("cy_cur_qtr"),
        qtd_py  = ts.get("py_cur_qtr"),
        ytd_cy  = ts.get("cy_ytd"),
        ytd_py  = ts.get("py_ytd"),
        monthly = [ts.get(f"cy_m{m:02d}") for m, _ in MONTHS],
    )

def _total_row(rows: list[dict]) -> dict:
    def _add(a, b):
        if a is None and b is None: return None
        return (a or 0) + (b or 0)
    total = dict(mo_cy=None, mo_py=None, qtd_cy=None, qtd_py=None,
                 ytd_cy=None, ytd_py=None, monthly=[None]*D_N_MONTHS)
    for r in rows:
        if r.get("is_header"): continue
        for k in ("mo_cy","mo_py","qtd_cy","qtd_py","ytd_cy","ytd_py"):
            total[k] = _add(total[k], r.get(k))
        for mi in range(D_N_MONTHS):
            mv = r.get("monthly", [None]*D_N_MONTHS)[mi]
            total["monthly"][mi] = _add(total["monthly"][mi], mv)
    return total

def _filter_opex(df: pd.DataFrame, entity: str,
                 proc_map: dict[str, list[str] | None]) -> pd.DataFrame:
    procs = proc_map.get(entity)
    if procs is not None:
        return df[df["process"].isin(procs)]
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# CELL WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def sc(ws: Worksheet, row: int, col: int, value: Any = None, *,
       bold: bool = False, fg: str = S.DATA_FG,
       bg: str | PatternFill = "FFFFFF",
       fmt: str | None = None, halign: str = "right",
       border: Border | None = None,
       italic: bool = False, size: int = 9) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.font      = S.font(bold=bold, color=fg, italic=italic, size=size)
    c.fill      = bg if isinstance(bg, PatternFill) else S.fill(bg)
    c.alignment = S.align(halign)
    if fmt    is not None: c.number_format = fmt
    if border is not None: c.border        = border


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION HEADER
# ═══════════════════════════════════════════════════════════════════════════════

def write_section_header(ws: Worksheet, row: int, label: str,
                         bg: str, fg: str,
                         height: int = 18,
                         bold: bool = True,
                         size: int = 9,
                         top_border: bool = False) -> None:
    for col in range(1, D_TOTAL + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = S.fill(bg)
        if top_border:
            cell.border = Border(top=S.HAIR)
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row,   end_column=D_TOTAL)
    c = ws.cell(row=row, column=1, value=label)
    c.font      = S.font(bold=bold, color=fg, size=size)
    c.fill      = S.fill(bg)
    c.alignment = S.align("left")
    ws.row_dimensions[row].height = height


# ═══════════════════════════════════════════════════════════════════════════════
# DATA ROW WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def write_data_row(ws: Worksheet, row: int, label: str,
                   mo_cy: float | None, mo_py: float | None,
                   qtd_cy: float | None, qtd_py: float | None,
                   ytd_cy: float | None, ytd_py: float | None,
                   monthly: list[float | None],
                   row_bg: str,
                   label_fg: str = S.DATA_FG,
                   bold: bool = False,
                   italic: bool = False,
                   data_fmt: str = FMT_USD,
                   var_fmt: str = FMT_VUSD,
                   indent: int = 0,
                   height: int = 15,
                   is_total: bool = False) -> None:

    mo_var  = (mo_cy  - mo_py  if mo_cy  is not None and mo_py  is not None else None)
    qtd_var = (qtd_cy - qtd_py if qtd_cy is not None and qtd_py is not None else None)
    ytd_var = (ytd_cy - ytd_py if ytd_cy is not None and ytd_py is not None else None)

    top = S.HAIR if is_total else None

    def _var_cell(r, col, v, rb):
        fill, fg = S.var_fill_fg(v, rb)
        cell = ws.cell(row=r, column=col, value=v)
        cell.font      = S.font(bold=bold, color=fg, size=9)
        cell.fill      = fill
        cell.alignment = S.align("right")
        cell.number_format = var_fmt
        if top:
            cell.border = Border(top=top)

    lbl = "  " * indent + label
    c = ws.cell(row=row, column=1, value=lbl)
    c.font      = S.font(bold=bold, color=label_fg, italic=italic, size=9)
    c.fill      = S.fill(row_bg)
    c.alignment = S.align("left")
    if top:
        c.border = Border(top=top)

    def _dc(col, val, fmt=data_fmt):
        cell = ws.cell(row=row, column=col, value=val)
        cell.font      = S.font(bold=bold, color=label_fg, size=9)
        cell.fill      = S.fill(row_bg)
        cell.alignment = S.align("right")
        cell.number_format = fmt
        if top:
            cell.border = Border(top=top)

    def _sep(col, sep_side):
        cell = ws.cell(row=row, column=col)
        cell.fill = S.fill(row_bg)
        cell.border = Border(right=sep_side, top=top) if top else Border(right=sep_side)

    _dc(D_MO_CY, mo_cy); _dc(D_MO_PY, mo_py)
    _var_cell(row, D_MO_VAR, mo_var, row_bg)
    _sep(D_SEP1, S.SEP)

    _dc(D_QTD_CY, qtd_cy); _dc(D_QTD_PY, qtd_py)
    _var_cell(row, D_QTD_VAR, qtd_var, row_bg)
    _sep(D_SEP2, S.SEP_QTD)

    _dc(D_YTD_CY, ytd_cy); _dc(D_YTD_PY, ytd_py)
    _var_cell(row, D_YTD_VAR, ytd_var, row_bg)
    _sep(D_SEP3, S.SEP)

    for mi, v in enumerate(monthly):
        is_last = (mi == D_N_MONTHS - 1)
        cell = ws.cell(row=row, column=d_mon_col(mi), value=v)
        cell.font      = S.font(color=S.MUTED_FG, size=8)
        cell.fill      = S.fill(row_bg)
        cell.alignment = S.align("right")
        cell.number_format = data_fmt
        if top:
            cell.border = Border(top=top,
                                 right=S.SEP_MON if is_last else None)
        elif is_last:
            cell.border = Border(right=S.SEP_MON)

    ws.row_dimensions[row].height = height


def write_total_row(ws: Worksheet, row: int, label: str,
                    data: dict,
                    row_bg: str = S.ROW_TOTAL,
                    label_fg: str = S.TOTAL_FG,
                    data_fmt: str = FMT_USD,
                    var_fmt: str = FMT_VUSD,
                    indent: int = 0,
                    height: int = 16) -> None:
    write_data_row(ws, row, label,
                   mo_cy=data.get("mo_cy"),   mo_py=data.get("mo_py"),
                   qtd_cy=data.get("qtd_cy"), qtd_py=data.get("qtd_py"),
                   ytd_cy=data.get("ytd_cy"), ytd_py=data.get("ytd_py"),
                   monthly=data.get("monthly", [None]*D_N_MONTHS),
                   row_bg=row_bg, label_fg=label_fg,
                   bold=True, data_fmt=data_fmt, var_fmt=var_fmt,
                   indent=indent, height=height, is_total=True)


# ═══════════════════════════════════════════════════════════════════════════════
# OPEX TYPE ROWS  +  GL account drill-down
# ═══════════════════════════════════════════════════════════════════════════════

def write_opex_types(ws: Worksheet, cur: int,
                     df: pd.DataFrame,
                     data_fmt: str = FMT_USD,
                     var_fmt: str = FMT_VUSD,
                     indent: int = 3) -> tuple[int, list[dict]]:
    if df.empty:
        return cur, []

    type_order = (df.groupby("type")["cy_ytd"]
                  .sum()
                  .sort_values(ascending=False)
                  .index.tolist())

    row_data: list[dict] = []
    for ti, type_name in enumerate(type_order):
        type_df = df[df["type"] == type_name]
        ts = _sum_type_group(type_df)
        rd = _row_from_summed(ts)
        row_data.append(rd)

        row_bg = S.ROW_EVEN if ti % 2 == 0 else S.ROW_ODD

        # ── summed type row — always visible ──────────────────────────────
        write_data_row(ws, cur, type_name,
                       mo_cy=rd["mo_cy"],   mo_py=rd["mo_py"],
                       qtd_cy=rd["qtd_cy"], qtd_py=rd["qtd_py"],
                       ytd_cy=rd["ytd_cy"], ytd_py=rd["ytd_py"],
                       monthly=rd["monthly"],
                       row_bg=row_bg,
                       label_fg=S.ITALIC_FG,
                       italic=True,
                       data_fmt=data_fmt,
                       var_fmt=var_fmt,
                       indent=indent)
        cur += 1

        # ── GL account drill-down rows — outline 1, collapsed ─────────────
        acct_order = (type_df.groupby("account_num")["cy_ytd"]
                      .sum()
                      .sort_values(ascending=False)
                      .index.tolist())

        for account_num in acct_order:
            acct_df  = type_df[type_df["account_num"] == account_num]
            ats      = _sum_type_group(acct_df)
            ard      = _row_from_summed(ats)

            # get GL description from first row
            desc = ""
            if "account_en" in acct_df.columns:
                val = acct_df["account_en"].iloc[0]
                if val and str(val).strip() not in ("", "nan", "None"):
                    desc = str(val).strip()

            acct_label = f"{account_num}  —  {desc}" if desc else account_num

            write_data_row(ws, cur, acct_label,
                           mo_cy=ard["mo_cy"],   mo_py=ard["mo_py"],
                           qtd_cy=ard["qtd_cy"], qtd_py=ard["qtd_py"],
                           ytd_cy=ard["ytd_cy"], ytd_py=ard["ytd_py"],
                           monthly=ard["monthly"],
                           row_bg=S.ROW_DRILL,
                           label_fg=S.DRILL_FG,
                           italic=True,
                           data_fmt=data_fmt,
                           var_fmt=var_fmt,
                           indent=indent + 1,
                           height=14)
            ws.row_dimensions[cur].outline_level = 1
            ws.row_dimensions[cur].hidden = True
            cur += 1

    return cur, row_data


# ═══════════════════════════════════════════════════════════════════════════════
# SPACER
# ═══════════════════════════════════════════════════════════════════════════════

def spacer(ws: Worksheet, cur: int, height: int = 4) -> int:
    ws.row_dimensions[cur].height = height
    for col in range(1, D_TOTAL + 1):
        ws.cell(row=cur, column=col).fill = S.fill("FFFFFF")
    return cur + 1


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def write_detail_headers(ws: Worksheet, entity: str) -> int:
    # Row 1 — title
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1,   end_column=D_TOTAL)
    c = ws.cell(row=1, column=1,
                value=f"Production Report  |  {entity}  |  "
                      f"{TODAY.strftime('%B %d, %Y')}")
    c.font      = S.font(bold=True, color=S.TITLE_FG, size=12)
    c.fill      = S.fill(S.TITLE_BG)
    c.alignment = S.align("center")
    ws.row_dimensions[1].height = 26

    # Row 2 — subtitle
    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2,   end_column=D_TOTAL)
    c = ws.cell(row=2, column=1,
                value=f"Volume in KG / DKG     ·     Costs in USD"
                      f"     ·     CY {CY}  vs  PY {PY}")
    c.font      = S.font(bold=False, color="90AABB", size=8)
    c.fill      = S.fill(S.TITLE_BG)
    c.alignment = S.align("center")
    ws.row_dimensions[2].height = 14

    # Row 3 — group headers
    for col in range(1, D_TOTAL + 1):
        ws.cell(row=3, column=col).fill = S.fill(S.TITLE_BG)

    def _grp(label, sc_idx, ec_idx, bg, fg, sep):
        ws.merge_cells(start_row=3, start_column=sc_idx,
                       end_row=3,   end_column=ec_idx)
        for col in range(sc_idx, ec_idx + 1):
            ws.cell(row=3, column=col).fill = S.fill(bg)
        c = ws.cell(row=3, column=sc_idx, value=label)
        c.font      = S.font(bold=False, color=fg, size=8)
        c.fill      = S.fill(bg)
        c.alignment = S.align("center")
        ws.cell(row=3, column=ec_idx).border = Border(right=sep)

    _grp("Current Month",   D_MO_CY,  D_SEP1, S.PERIOD_BG, S.PERIOD_FG, S.SEP)
    _grp("Quarter To Date", D_QTD_CY, D_SEP2, S.QTD_BG,    S.QTD_FG,    S.SEP_QTD)
    _grp("Year To Date",    D_YTD_CY, D_SEP3, S.PERIOD_BG, S.PERIOD_FG, S.SEP)

    ws.merge_cells(start_row=3, start_column=D_MON_START,
                   end_row=3,   end_column=D_TOTAL)
    for col in range(D_MON_START, D_TOTAL + 1):
        ws.cell(row=3, column=col).fill = S.fill(S.MON_BG)
    c = ws.cell(row=3, column=D_MON_START,
                value=f"Monthly Actuals  ·  CY {CY}")
    c.font      = S.font(bold=False, color=S.MON_FG, size=8)
    c.fill      = S.fill(S.MON_BG)
    c.alignment = S.align("center")
    ws.cell(row=3, column=D_TOTAL).border = Border(right=S.SEP_MON)
    ws.row_dimensions[3].height = 18

    # Row 4 — sub-headers
    sc(ws, 4, 1, "Metric", bold=True, fg=S.HDR_FG,
       bg=S.HDR_BG, halign="left", size=8)

    def _sub(cy_c, py_c, var_c, sep_c, sep):
        for col, lbl in [(cy_c, f"CY {CY}"),
                         (py_c, f"PY {PY}"),
                         (var_c, "Var $")]:
            c = ws.cell(row=4, column=col, value=lbl)
            c.font      = S.font(bold=True, color=S.HDR_FG, size=8)
            c.fill      = S.fill(S.HDR_BG)
            c.alignment = S.align("center")
        sc(ws, 4, sep_c, None, bg=S.HDR_BG,
           border=Border(right=sep))

    _sub(D_MO_CY,  D_MO_PY,  D_MO_VAR,  D_SEP1, S.SEP)
    _sub(D_QTD_CY, D_QTD_PY, D_QTD_VAR, D_SEP2, S.SEP_QTD)
    _sub(D_YTD_CY, D_YTD_PY, D_YTD_VAR, D_SEP3, S.SEP)

    for mi, (_, m_label) in enumerate(MONTHS):
        c = ws.cell(row=4, column=d_mon_col(mi), value=m_label)
        c.font      = S.font(bold=False, color="8FA3B1", size=7)
        c.fill      = S.fill(S.HDR_BG)
        c.alignment = S.align("center")
        if mi == D_N_MONTHS - 1:
            c.border = Border(right=S.SEP_MON)
    ws.row_dimensions[4].height = 22

    ws.column_dimensions["A"].width = 42
    for col_idx in [D_MO_CY, D_MO_PY, D_MO_VAR,
                    D_QTD_CY, D_QTD_PY, D_QTD_VAR,
                    D_YTD_CY, D_YTD_PY, D_YTD_VAR]:
        ws.column_dimensions[get_column_letter(col_idx)].width = 12
    for sep_idx in [D_SEP1, D_SEP2, D_SEP3]:
        ws.column_dimensions[get_column_letter(sep_idx)].width = 1
    for mi in range(D_N_MONTHS):
        ws.column_dimensions[get_column_letter(d_mon_col(mi))].width = 7

    return 5


# ═══════════════════════════════════════════════════════════════════════════════
# ENTITY TAB BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_entity_tab(wb: Workbook, entity: str,
                     vc_df: pd.DataFrame,
                     opex_df: pd.DataFrame) -> None:

    ws  = wb.create_sheet(title=entity)
    cur = write_detail_headers(ws, entity)

    vc_e   = vc_df[vc_df["entity"]   == entity].copy()
    opex_e = opex_df[opex_df["entity"] == entity].copy()

    opex_var_fix = _filter_opex(opex_e, entity, ENTITY_VAR_FIX_OH_PROCESS)
    opex_dm      = _filter_opex(opex_e, entity, ENTITY_DM_PROCESS)
    opex_abs     = _filter_opex(opex_e, entity, ENTITY_ABS_PROCESS)

    # ── SECTION 1: VOLUME ────────────────────────────────────────────────────
    write_section_header(ws, cur, "  VOLUME",
                         S.SECT_BG, S.SECT_FG, height=20, size=9)
    cur += 1

    for vi, (label, cy_base, py_base, dfmt, vfmt) in enumerate([
        ("Volume (KG)",  "cy_vol_kg",  "py_vol_kg",  FMT_VOL, FMT_VUSD),
        ("Volume (DKG)", "cy_vol_dkg", "py_vol_dkg", FMT_VOL, FMT_VUSD),
    ]):
        row_bg = S.ROW_EVEN if vi % 2 == 0 else S.ROW_ODD
        write_data_row(ws, cur, label,
                       mo_cy =_sum(vc_e, f"{cy_base}_cur_month"),
                       mo_py =_sum(vc_e, f"{py_base}_cur_month"),
                       qtd_cy=_sum(vc_e, f"{cy_base}_cur_qtr"),
                       qtd_py=_sum(vc_e, f"{py_base}_cur_qtr"),
                       ytd_cy=_sum(vc_e, f"{cy_base}_ytd"),
                       ytd_py=_sum(vc_e, f"{py_base}_ytd"),
                       monthly=_build_monthly(vc_e, cy_base),
                       row_bg=row_bg, bold=True, indent=2,
                       data_fmt=dfmt, var_fmt=vfmt)
        cur += 1

    cur = spacer(ws, cur, 6)

    # ── SECTION 2: COST OF PRODUCTION ────────────────────────────────────────
    write_section_header(ws, cur, "  COST OF PRODUCTION",
                         S.SECT_BG, S.SECT_FG, height=20, size=9)
    cur += 1

    # ── 2a. Direct Material ───────────────────────────────────────────────────
    write_section_header(ws, cur, "    Direct Material",
                         S.SUB_BG, S.SUB_FG,
                         height=16, bold=True, size=9)
    cur += 1

    dm_df = opex_dm[opex_dm["category"] == CAT_DM]
    cur, dm_rows = write_opex_types(ws, cur, dm_df, indent=3)
    dm_total = _total_row(dm_rows)
    write_total_row(ws, cur, "      Total Direct Material",
                    dm_total, indent=0)
    cur += 1
    cur = spacer(ws, cur, 4)

    # ── 2b. Overhead ──────────────────────────────────────────────────────────
    write_section_header(ws, cur, "    Overhead",
                         S.SUB_BG, S.SUB_FG,
                         height=16, bold=True, size=9)
    cur += 1

    # Variable
    write_section_header(ws, cur, "      Variable",
                         S.SUBSUB_BG, S.SUBSUB_FG,
                         height=15, bold=True, size=9)
    cur += 1

    var_df = opex_var_fix[opex_var_fix["category"] == CAT_VAR]
    cur, var_rows = write_opex_types(ws, cur, var_df, indent=4)
    var_total = _total_row(var_rows)
    write_total_row(ws, cur, "        Total Variable", var_total, indent=0)
    cur += 1
    cur = spacer(ws, cur, 4)

    # Fixed
    write_section_header(ws, cur, "      Fixed",
                         S.SUBSUB_BG, S.SUBSUB_FG,
                         height=15, bold=True, size=9)
    cur += 1

    fix_df = opex_var_fix[opex_var_fix["category"] == CAT_FIX]
    cur, fix_rows = write_opex_types(ws, cur, fix_df, indent=4)
    fix_total = _total_row(fix_rows)
    write_total_row(ws, cur, "        Total Fixed", fix_total, indent=0)
    cur += 1
    cur = spacer(ws, cur, 4)

    # Total Overhead
    oh_total = _total_row([var_total, fix_total])
    write_total_row(ws, cur, "      Total Overhead", oh_total,
                    row_bg=S.SUB_BG, label_fg=S.SUB_FG, indent=0)
    cur += 1
    cur = spacer(ws, cur, 4)

    # ── 2c. Unit Cost (placeholder) ───────────────────────────────────────────
    write_section_header(ws, cur, "    Unit Cost",
                         S.SUB_BG, S.SUB_FG,
                         height=16, bold=True, size=9)
    cur += 1
    for vi, label in enumerate(["Material", "Var OH", "Fixed OH", "Total"]):
        row_bg = S.ROW_EVEN if vi % 2 == 0 else S.ROW_ODD
        write_data_row(ws, cur, label,
                       None, None, None, None, None, None,
                       [None]*D_N_MONTHS,
                       row_bg=row_bg, indent=3)
        cur += 1
    cur = spacer(ws, cur, 4)

    # ── 2d. Standard Absorption ───────────────────────────────────────────────
    write_section_header(ws, cur, "    Standard Absorption",
                         S.SUB_BG, S.SUB_FG,
                         height=16, bold=True, size=9)
    cur += 1

    abs_df = opex_abs[opex_abs["category"] == CAT_ABS]
    cur, abs_rows = write_opex_types(ws, cur, abs_df, indent=3)
    abs_total = _total_row(abs_rows)
    write_total_row(ws, cur, "      Total", abs_total, indent=0)
    cur += 1

    cur = spacer(ws, cur, 8)

    # ── SECTION 3: VOLUME BY PROCESS ─────────────────────────────────────────
    write_section_header(ws, cur, "  VOLUME BY PROCESS",
                         S.SECT_BG, S.SECT_FG, height=20, size=9)
    cur += 1

    all_processes = sorted(
        vc_e["absorption_category"].unique().tolist(),
        key=lambda p: (1 if p in BOTTOM_PROCESSES else 0, p)
    )

    for pi, process in enumerate(all_processes):
        proc_vc = vc_e[vc_e["absorption_category"] == process]
        row_bg  = S.ROW_PROC if pi % 2 == 0 else S.ROW_ODD
        write_data_row(ws, cur, process,
                       mo_cy =_sum(proc_vc, "cy_vol_kg_cur_month"),
                       mo_py =_sum(proc_vc, "py_vol_kg_cur_month"),
                       qtd_cy=_sum(proc_vc, "cy_vol_kg_cur_qtr"),
                       qtd_py=_sum(proc_vc, "py_vol_kg_cur_qtr"),
                       ytd_cy=_sum(proc_vc, "cy_vol_kg_ytd"),
                       ytd_py=_sum(proc_vc, "py_vol_kg_ytd"),
                       monthly=_build_monthly(proc_vc, "cy_vol_kg"),
                       row_bg=row_bg, indent=2,
                       data_fmt=FMT_VOL, var_fmt=FMT_VUSD)
        cur += 1

    ws.freeze_panes = "B5"
    ws.sheet_properties.outlinePr.summaryBelow = False
    ws.sheet_properties.outlinePr.summaryRight = False
    S.apply_outer_border(ws, 1, cur - 1, 1, D_TOTAL)
    print(f"  Tab [{entity}] → row {cur - 1}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    loader = Loader()
    try:
        vc_df   = loader.load_volume_cost()
        opex_df = loader.load_opex()
    finally:
        loader.close()

    wb = Workbook()
    wb.remove(wb.active)

    for entity in ENTITIES:
        build_entity_tab(wb, entity, vc_df, opex_df)

    wb.save(OUTPUT_FILE)
    print(f"\nSaved → {OUTPUT_FILE}")
    print(f"Tabs:  {[ws.title for ws in wb.worksheets]}")


if __name__ == "__main__":
    main()