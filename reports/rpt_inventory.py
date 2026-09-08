#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# inventory_report.py
#
# Bank-ready inventory valuation workbook from FCT_GLOBAL_INVENTORY.
#
# Layout:
#   Category Summary     pivot: 4 named categories as rows, databases as column
#                        groups; drill to package → facility → lot
#   Inventory Summary    value table (on-hand kg + extended USD by entity →
#                        product class → package)
#   <ENTITY> tabs        collapsible drill: class → package → facility → lot
#   Exchange Rates       implied local-per-USD rate per entity
#
# Output is split into three workbooks:
#   INVENTORY_OUTPUT_PATH  Category Summary, Inventory Summary, entity tabs,
#                          Exchange Rates — identical to the original
#                          single-workbook layout, just its own file
#   MOVEMENT_OUTPUT_PATH   REMELTS Movement (first tab) + per-entity
#                          Movement tabs
#   FACILITY_OUTPUT_PATH   <ENTITY> by Warehouse tabs: "Inventory Report by
#                          Warehouse", drilling Facility -> Package -> Lot,
#                          WP-basis cost (warehouse-first; different from
#                          the inventory workbook's Class -> Package ->
#                          Facility -> Lot entity tabs)
#
# Environment variables required:
#   DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from databricks import sql as databricks_sql

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

DBX_SERVER_HOSTNAME = os.environ["DATABRICKS_SERVER_HOSTNAME"]
DBX_HTTP_PATH       = os.environ["DATABRICKS_HTTP_PATH"]
DBX_ACCESS_TOKEN    = os.environ["DATABRICKS_TOKEN"]
DBX_CATALOG         = "prod"
DBX_SCHEMA          = "gold_sales"   # matches FCT_GLOBAL_SALES_ORDERS_2's schema; supply-chain tables below are qualified explicitly since they're a different schema

# NOTE: FCT_GLOBAL_INVENTORY and FCT_GLOBAL_INVENTORY_CHANGE have not been
# confirmed to exist in the new Databricks workspace yet -- prod.gold_supply_chain
# schema exists (created empty, matching dbt_project.yml's marts.supply_chain
# block) but no dbt models have been built to populate it in this migration
# yet. This is the same situation OneStream/HR/production-cost turned out to
# be: a separate migration thread, not just a catalog/schema rename. Confirm
# these tables are actually populated before relying on this report's output.
SOURCE_TABLE   = f"{DBX_CATALOG}.gold_supply_chain.fct_global_inventory"
SALES_TABLE    = f"{DBX_CATALOG}.gold_sales.fct_global_sales_orders_2"
MOVEMENT_TABLE = f"{DBX_CATALOG}.gold_supply_chain.fct_global_inventory_change"

# Rolling-12-month window for sales velocity (months on hand)
TODAY      = datetime.now().date()
R12M_START = TODAY - timedelta(days=365)

# Tab order. Entities not listed here are appended after, alphabetically.
ENTITY_ORDER = ["US", "CHINA", "WEIFENG", "EVD", "CHILE"]

# Category tab order — only these 4 are rendered; anything else is excluded.
CATEGORY_ORDER = [
    "CRUDE DERIVATIVES",
    "DERIVATIVES BYPRODUCTS",
    "MAGNASWEET",
    "REMELTS",
]

INVENTORY_OUTPUT_PATH = os.environ.get(
    "INVENTORY_REPORT_PATH",
    f"inventory_report_{datetime.now():%Y%m%d}.xlsx",
)
MOVEMENT_OUTPUT_PATH = os.environ.get(
    "MOVEMENT_REPORT_PATH",
    f"movement_report_{datetime.now():%Y%m%d}.xlsx",
)
FACILITY_OUTPUT_PATH = os.environ.get(
    "FACILITY_REPORT_PATH",
    f"facility_report_{datetime.now():%Y%m%d}.xlsx",
)

# Number formats
FMT_KG   = "#,##0"
FMT_COST = "#,##0.0000"
FMT_USD  = '$#,##0'
FMT_PCT  = "0.0%"
FMT_MOH  = "#,##0.0"
FMT_MOVE = "#,##0;(#,##0)"

# Palette
NAVY  = "1F3864"
STEEL = "2E5496"
LIGHT = "D9E1F2"
ZEBRA = "F2F5FB"
GREY  = "808080"

THIN   = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ═══════════════════════════════════════════════════════════════════════════════
# LOADER
# ═══════════════════════════════════════════════════════════════════════════════

class InventoryLoader:
    """Pulls FCT_GLOBAL_INVENTORY, cleans types, drops zero/inactive rows."""

    def __init__(self):
        self._conn = databricks_sql.connect(
            server_hostname = DBX_SERVER_HOSTNAME,
            http_path       = DBX_HTTP_PATH,
            access_token    = DBX_ACCESS_TOKEN,
            catalog         = DBX_CATALOG,
            schema          = DBX_SCHEMA,
        )

    def close(self):
        self._conn.close()
        print("  Databricks connection closed.")

    def _query(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(rows, columns=cols)

    def load(self):
        print(f"  Loading {SOURCE_TABLE} ...")
        df = self._query(f"""
            SELECT
                DATABASE,
                PRODUCT_DIVISION,
                PRODUCT_CLASS,
                PRODUCT_CATEGORY,
                PRODUCT_CODE,
                PROD_PKG_CODE,
                PRODUCT_NAME,
                FACILITY,
                UNIT_OF_MEAS,
                ACTIVE,
                LOT_CODE,
                LOT_SUPPLIER_LOT_CODE,
                SUPPLIER_NAME,
                SUPPLIER_CODE,
                LOT_CREATED_DATE,
                LOT_EXPIRATION_DATE,
                DAYS_OLD,
                QTY_IN_KG,
                QTY_IN_DKG,
                COST_KG,
                COST_KG_WP,
                COST_KG_PP,
                COST_KG_USD,
                COST_DKG,
                DRY_PERCENT,
                EXTENSION,
                EXTENSION_USD,
                EXTENSION_WP,
                EXTENSION_WP_USD,
                EXTENSION_PP,
                EXTENSION_PP_USD,
                COST_DKG_WP,
                COST_DKG_PP,
                COST_DKG_WP_USD,
                COST_DKG_PP_USD
            FROM {SOURCE_TABLE}
            WHERE QTY_IN_KG > 0
        """)
        print(f"    {len(df):,} on-hand rows")

        # Numeric coercion (Snowflake driver may return Decimal)
        for col in ["QTY_IN_KG", "QTY_IN_DKG", "COST_KG", "COST_KG_WP", "COST_KG_PP",
                    "COST_KG_USD", "COST_DKG", "DRY_PERCENT",
                    "EXTENSION", "EXTENSION_USD", "EXTENSION_WP", "EXTENSION_WP_USD",
                    "EXTENSION_PP", "EXTENSION_PP_USD", "COST_DKG_WP", "COST_DKG_PP",
                    "COST_DKG_WP_USD", "COST_DKG_PP_USD", "DAYS_OLD"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # String cleaning
        for col in ["DATABASE", "PRODUCT_DIVISION", "PRODUCT_CLASS",
                    "PRODUCT_CATEGORY", "PRODUCT_CODE", "PROD_PKG_CODE",
                    "PRODUCT_NAME", "FACILITY", "UNIT_OF_MEAS", "LOT_CODE",
                    "LOT_SUPPLIER_LOT_CODE", "SUPPLIER_NAME", "SUPPLIER_CODE"]:
            df[col] = (df[col].astype(str).str.strip()
                       .replace({"nan": "", "None": ""}).fillna(""))

        df["PRODUCT_DIVISION"] = df["PRODUCT_DIVISION"].replace({"": "(no division)"})
        df["PRODUCT_CLASS"]    = df["PRODUCT_CLASS"].replace({"": "(no class)"})
        df["PRODUCT_CATEGORY"] = df["PRODUCT_CATEGORY"].replace({"": "(uncategorized)"})

        # Lot dates
        for col in ["LOT_CREATED_DATE", "LOT_EXPIRATION_DATE"]:
            df[col] = pd.to_datetime(df[col], errors="coerce")

        # Active filter — tolerant of bool or string storage
        active = df["ACTIVE"].astype(str).str.strip().str.upper()
        df = df[active.isin(["TRUE", "T", "1", "Y", "YES"])].copy()
        print(f"    {len(df):,} active rows")

        # ── 12M sales velocity → months on hand ──────────────────────────────
        print(f"  Loading 12M sales ({R12M_START} .. {TODAY}) ...")
        sales = self._query(f"""
            SELECT DATABASE, PROD_PKG_CODE, SUM(QTY_IN_KG) AS SALES_12M_KG
            FROM {SALES_TABLE}
            WHERE INVOICE_DATE >= '{R12M_START.isoformat()}'
              AND INVOICE_DATE  < '{TODAY.isoformat()}'
            GROUP BY 1, 2
        """)
        sales["SALES_12M_KG"] = pd.to_numeric(sales["SALES_12M_KG"],
                                               errors="coerce").fillna(0)
        for col in ["DATABASE", "PROD_PKG_CODE"]:
            sales[col] = sales[col].astype(str).str.strip()
        print(f"    {len(sales):,} package-level sales rows")

        df = df.merge(sales, on=["DATABASE", "PROD_PKG_CODE"], how="left")
        df["SALES_12M_KG"] = df["SALES_12M_KG"].fillna(0)
        pkg_qty = df.groupby(["DATABASE", "PROD_PKG_CODE"])["QTY_IN_KG"].transform("sum")
        df["SALES_12M_ALLOC"] = (
            df["SALES_12M_KG"] * df["QTY_IN_KG"] / pkg_qty.where(pkg_qty > 0)
        ).fillna(0)

        # Entity sort key
        order = {e: i for i, e in enumerate(ENTITY_ORDER)}
        df["_ENTITY_ORD"] = df["DATABASE"].map(lambda e: order.get(e, 999))
        df = df.sort_values(
            ["_ENTITY_ORD", "DATABASE", "PRODUCT_DIVISION", "PRODUCT_CLASS",
             "PRODUCT_CODE", "PROD_PKG_CODE", "FACILITY", "LOT_CREATED_DATE"]
        ).reset_index(drop=True)
        return df

    def load_movement(self, inv_df):
        """Prior-month net movement by entity x package (model already filters
        to the prior period via its own prior_period CTE)."""
        print(f"  Loading {MOVEMENT_TABLE} ...")
        m = self._query(f"""
            SELECT SOURCE_DATABASE, PROD_PKG_CODE, PRODUCT_CLASS, PRODUCT_NAME,
                PRODUCTION_KG, PRODUCTION_DKG, PURCHASE_KG, SALES_KG,
                WAREHOUSE_TRANSFER_KG, OTHER_KG, TOTAL_NET_KG,
                START_PERIOD, END_PERIOD
            FROM {MOVEMENT_TABLE}
        """)
        print(f"    {len(m):,} movement rows")
        if m.empty:
            return m

        m = m.rename(columns={"SOURCE_DATABASE": "DATABASE"})
        for c in ["PRODUCTION_KG", "PRODUCTION_DKG", "PURCHASE_KG", "SALES_KG",
                  "WAREHOUSE_TRANSFER_KG", "OTHER_KG", "TOTAL_NET_KG"]:
            m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0)
        for c in ["DATABASE", "PROD_PKG_CODE"]:
            m[c] = m[c].astype(str).str.strip()
        m["PRODUCT_CLASS"] = (m["PRODUCT_CLASS"].astype(str).str.strip()
                               .replace({"nan": "", "None": ""}).fillna(""))
        m["PRODUCT_CLASS"] = m["PRODUCT_CLASS"].replace({"": "(unclassified)"})
        m["PRODUCT_NAME"]  = (m["PRODUCT_NAME"].astype(str).str.strip()
                               .replace({"nan": "", "None": ""}).fillna(""))

        order = {e: i for i, e in enumerate(ENTITY_ORDER)}
        m["_ENTITY_ORD"] = m["DATABASE"].map(lambda e: order.get(e, 999))
        m["_ABSNET"] = m["TOTAL_NET_KG"].abs()
        m = m.sort_values(["_ENTITY_ORD", "PRODUCT_CLASS", "_ABSNET"],
                          ascending=[True, True, False]).reset_index(drop=True)
        return m


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

class ReportBuilder:
    """Renders three workbooks from a single FCT_GLOBAL_INVENTORY DataFrame:
    inventory (Category Summary, Inventory Summary, entity tabs, Exchange
    Rates — unchanged from the original single-workbook layout), movement
    (REMELTS Movement + per-entity Movement tabs), and facility
    (warehouse-first "Inventory Report by Warehouse" entity tabs, drilling
    Facility -> Package -> Lot)."""

    def __init__(self, df, move=None):
        self.df = df
        self.move = move

        self.wb_inventory = Workbook()
        self.wb_inventory.remove(self.wb_inventory.active)

        self.wb_movement = Workbook()
        self.wb_movement.remove(self.wb_movement.active)

        self.wb_facility = Workbook()
        self.wb_facility.remove(self.wb_facility.active)

        self.grand_usd = float(df["EXTENSION_PP_USD"].sum())

    # ── styling helpers ────────────────────────────────────────────────────────
    def _title(self, ws, text, sub, ncols):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        c = ws.cell(1, 1, text)
        c.font = Font(bold=True, size=14, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 24
        if sub:
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
            s = ws.cell(2, 1, sub)
            s.font = Font(italic=True, size=9, color=GREY)

    def _header(self, ws, row, headers):
        for j, h in enumerate(headers, start=1):
            c = ws.cell(row, j, h)
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor=STEEL)
            c.alignment = Alignment(horizontal="center", vertical="center",
                                    wrap_text=True)
            c.border = BORDER
        ws.row_dimensions[row].height = 28

    def _val(self, ws, row, col, value, fmt=None, bold=False, fill=None,
             align="right", indent=0, color=None):
        c = ws.cell(row, col, value)
        c.font = Font(bold=bold, size=10, color=color or "000000")
        if fmt:
            c.number_format = fmt
        c.alignment = Alignment(horizontal=align, vertical="center", indent=indent)
        if fill:
            c.fill = PatternFill("solid", fgColor=fill)
        c.border = BORDER
        return c

    # ── CATEGORY SUMMARY TAB (original — unchanged) ───────────────────────────
    def build_category(self, cdf):
        """
        Single pivot tab — 4 named categories as rows, databases as column groups.
        Drill: Category (L0) -> Product-Package (L1) -> Facility (L2) -> Lot (L3).
        Cost/dkg is blank at category level (weighted avg across mixed products
        is not meaningful). Facility/lot rows only populate their own database
        column group + the All group.
        """
        ws = self.wb_inventory.create_sheet("Category Summary")

        present = set(cdf["DATABASE"])
        dbs     = [e for e in ENTITY_ORDER if e in present]
        dbs    += sorted(present - set(dbs))
        groups  = dbs + ["All"]

        SUBCOLS = ["On-hand (kg)", "On-hand (dkg)", "Cost/dkg (USD)", "Ext (USD)"]
        NSUB    = len(SUBCOLS)
        ncols   = 2 + len(groups) * NSUB

        self._title(ws,
                    "Inventory by Product Category"
                    f"   |   Generated {datetime.now():%Y-%m-%d}",
                    None, ncols)

        # ── two-row header ─────────────────────────────────────────────────────
        hr1, hr2 = 4, 5
        for col, label in [(1, "Category / Package / Lot"), (2, "Product Name")]:
            ws.merge_cells(start_row=hr1, start_column=col,
                           end_row=hr2, end_column=col)
            c = ws.cell(hr1, col, label)
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor=STEEL)
            c.alignment = Alignment(horizontal="center", vertical="center",
                                    wrap_text=True)
            c.border = BORDER

        for gi, grp in enumerate(groups):
            start = 3 + gi * NSUB
            shade = NAVY if grp == "All" else STEEL
            ws.merge_cells(start_row=hr1, start_column=start,
                           end_row=hr1, end_column=start + NSUB - 1)
            gc = ws.cell(hr1, start, "All Entities" if grp == "All" else grp)
            gc.font = Font(bold=True, color="FFFFFF", size=10)
            gc.fill = PatternFill("solid", fgColor=shade)
            gc.alignment = Alignment(horizontal="center", vertical="center")
            gc.border = BORDER
            for si, sub in enumerate(SUBCOLS):
                c = ws.cell(hr2, start + si, sub)
                c.font = Font(bold=True, color="FFFFFF", size=9)
                c.fill = PatternFill("solid", fgColor=shade)
                c.alignment = Alignment(horizontal="center", vertical="center",
                                        wrap_text=True)
                c.border = BORDER

        ws.row_dimensions[hr1].height = 18
        ws.row_dimensions[hr2].height = 28
        ws.sheet_properties.outlinePr.summaryBelow = False

        # ── column writer helper ───────────────────────────────────────────────
        def write_group(row, start, sub, fill=None, bold=False, color=None,
                        show_cost=True):
            if sub.empty:
                for si in range(NSUB):
                    self._val(ws, row, start + si, "", fill=fill)
                return
            qty  = float(sub["QTY_IN_KG"].sum())
            dqty = float(sub["QTY_IN_DKG"].sum())
            ext  = float(sub["EXTENSION_PP_USD"].sum())
            cdkg = (ext / dqty if dqty else None) if show_cost else None
            self._val(ws, row, start + 0, qty,  FMT_KG,   bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 1, dqty, FMT_KG,   bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 2, cdkg, FMT_COST, bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 3, ext,  FMT_USD,  bold=bold, fill=fill, color=color)

        # ── body ───────────────────────────────────────────────────────────────
        r = hr2 + 1

        for cat in CATEGORY_ORDER:
            cat_rows = cdf[cdf["PRODUCT_CATEGORY"] == cat]
            if cat_rows.empty:
                continue

            # ── Category (L0, always visible) — cost/dkg intentionally blank ──
            self._val(ws, r, 1, cat, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, 2, "",  fill=LIGHT)
            for gi, grp in enumerate(groups):
                start = 3 + gi * NSUB
                sub = cat_rows if grp == "All" else cat_rows[cat_rows["DATABASE"] == grp]
                write_group(r, start, sub, fill=LIGHT, bold=True, show_cost=False)
            r += 1

            for pkg, pkg_rows in cat_rows.groupby("PROD_PKG_CODE", sort=False):
                name = pkg_rows["PRODUCT_NAME"].iloc[0]

                # ── Product-Package (L1, collapsible) — weighted avg cost ──────
                self._val(ws, r, 1, pkg,  bold=True, align="left", indent=1)
                self._val(ws, r, 2, name, bold=True, align="left")
                for gi, grp in enumerate(groups):
                    start = 3 + gi * NSUB
                    sub = pkg_rows if grp == "All" else pkg_rows[pkg_rows["DATABASE"] == grp]
                    write_group(r, start, sub, bold=True, show_cost=True)
                ws.row_dimensions[r].outline_level = 1
                r += 1

                for (db, fac), fac_rows in pkg_rows.groupby(
                        ["DATABASE", "FACILITY"], sort=False):
                    # ── Facility (L2, hidden) — WP cost; own db + All only ─────
                    qty_f  = float(fac_rows["QTY_IN_KG"].sum())
                    dqty_f = float(fac_rows["QTY_IN_DKG"].sum())
                    ext_f  = float(fac_rows["EXTENSION_WP_USD"].sum())
                    cdkg_f = (ext_f / dqty_f if dqty_f else None)

                    self._val(ws, r, 1, f"{db} - {fac}", align="left", indent=2)
                    self._val(ws, r, 2, name, align="left")
                    for gi, grp in enumerate(groups):
                        col_start = 3 + gi * NSUB
                        if grp == "All" or grp == db:
                            self._val(ws, r, col_start + 0, qty_f,  FMT_KG)
                            self._val(ws, r, col_start + 1, dqty_f, FMT_KG)
                            self._val(ws, r, col_start + 2, cdkg_f, FMT_COST)
                            self._val(ws, r, col_start + 3, ext_f,  FMT_USD)
                        else:
                            for si in range(NSUB):
                                self._val(ws, r, col_start + si, "")
                    ws.row_dimensions[r].outline_level = 2
                    ws.row_dimensions[r].hidden = True
                    r += 1

                    for _, lot_row in fac_rows.iterrows():
                        # ── Lot (L3, hidden) — lot-actual cost; own db + All ───
                        zebra  = ZEBRA if r % 2 == 0 else None
                        qty_l  = float(lot_row["QTY_IN_KG"])
                        dqty_l = float(lot_row["QTY_IN_DKG"])
                        ext_l  = float(lot_row["EXTENSION_USD"])
                        cost_l = float(lot_row["COST_DKG"])

                        self._val(ws, r, 1,
                                  lot_row["LOT_CODE"] or "(no lot)",
                                  align="left", indent=3, fill=zebra)
                        self._val(ws, r, 2, "", fill=zebra)
                        for gi, grp in enumerate(groups):
                            col_start = 3 + gi * NSUB
                            if grp == "All" or grp == db:
                                self._val(ws, r, col_start + 0, qty_l,  FMT_KG,   fill=zebra)
                                self._val(ws, r, col_start + 1, dqty_l, FMT_KG,   fill=zebra)
                                self._val(ws, r, col_start + 2, cost_l, FMT_COST, fill=zebra)
                                self._val(ws, r, col_start + 3, ext_l,  FMT_USD,  fill=zebra)
                            else:
                                for si in range(NSUB):
                                    self._val(ws, r, col_start + si, "", fill=zebra)
                        ws.row_dimensions[r].outline_level = 3
                        ws.row_dimensions[r].hidden = True
                        r += 1

        # ── Grand total ────────────────────────────────────────────────────────
        self._val(ws, r, 1, "GRAND TOTAL", bold=True, fill=STEEL,
                  align="left", color="FFFFFF")
        self._val(ws, r, 2, "", fill=STEEL)
        for gi, grp in enumerate(groups):
            start = 3 + gi * NSUB
            sub = cdf if grp == "All" else cdf[cdf["DATABASE"] == grp]
            write_group(r, start, sub, fill=STEEL, bold=True,
                        color="FFFFFF", show_cost=True)

        # ── Column widths ──────────────────────────────────────────────────────
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 28
        for gi in range(len(groups)):
            start = 3 + gi * NSUB
            for si, w in enumerate([13, 13, 13, 15]):
                ws.column_dimensions[get_column_letter(start + si)].width = w
        ws.freeze_panes = "C6"

    # ── INVENTORY SUMMARY (original — unchanged) ──────────────────────────────
    def build_summary(self):
        ws = self.wb_inventory.create_sheet("Inventory Summary")

        present  = set(self.df["DATABASE"])
        entities = [e for e in ENTITY_ORDER if e in present]
        entities += sorted(present - set(entities))
        groups   = entities + ["All"]

        d = self.df.copy()
        d["_DRY_KG"] = d["QTY_IN_KG"] * d["DRY_PERCENT"]

        SUBCOLS = ["On-hand (kg)", "Cost/dkg (USD)", "Ext (USD)", "MOH"]
        NSUB    = len(SUBCOLS)
        ncols   = 2 + len(groups) * NSUB

        self._title(ws,
                    "Global Inventory - Valuation Summary"
                    f"   |   Generated {datetime.now():%Y-%m-%d}",
                    None, ncols)

        # ── two-row header ─────────────────────────────────────────────────────
        hr1, hr2 = 4, 5
        for col, label in [(1, "Product Package"), (2, "Product Name")]:
            ws.merge_cells(start_row=hr1, start_column=col,
                           end_row=hr2, end_column=col)
            c = ws.cell(hr1, col, label)
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor=STEEL)
            c.alignment = Alignment(horizontal="center", vertical="center",
                                    wrap_text=True)
            c.border = BORDER
        for gi, grp in enumerate(groups):
            start = 3 + gi * NSUB
            shade = NAVY if grp == "All" else STEEL
            ws.merge_cells(start_row=hr1, start_column=start,
                           end_row=hr1, end_column=start + NSUB - 1)
            gc = ws.cell(hr1, start, "All Entities" if grp == "All" else grp)
            gc.font = Font(bold=True, color="FFFFFF", size=10)
            gc.fill = PatternFill("solid", fgColor=shade)
            gc.alignment = Alignment(horizontal="center", vertical="center")
            gc.border = BORDER
            for si, sub in enumerate(SUBCOLS):
                c = ws.cell(hr2, start + si, sub)
                c.font = Font(bold=True, color="FFFFFF", size=9)
                c.fill = PatternFill("solid", fgColor=shade)
                c.alignment = Alignment(horizontal="center", vertical="center",
                                        wrap_text=True)
                c.border = BORDER
        ws.row_dimensions[hr1].height = 18
        ws.row_dimensions[hr2].height = 28
        ws.sheet_properties.outlinePr.summaryBelow = False

        def write_group(row, start, sub, fill=None, bold=False, color=None,
                        show_cost=True):
            if sub.empty:
                for si in range(NSUB):
                    self._val(ws, row, start + si, "", fill=fill)
                return
            onhand = float(sub["QTY_IN_KG"].sum())
            ext_pp = float(sub["EXTENSION_PP_USD"].sum())
            dry_kg = float(sub["_DRY_KG"].sum())
            s12    = float(sub["SALES_12M_ALLOC"].sum())
            # cost/dkg and MOH suppressed at class level — not meaningful
            # to average across mixed products
            cdkg = (ext_pp / dry_kg if dry_kg else None) if show_cost else None
            moh  = (onhand / (s12 / 12.0) if s12 > 0 else None) if show_cost else None
            self._val(ws, row, start + 0, onhand, FMT_KG,   bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 1, cdkg,   FMT_COST, bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 2, ext_pp, FMT_USD,  bold=bold, fill=fill, color=color)
            self._val(ws, row, start + 3, moh,    FMT_MOH,  bold=bold, fill=fill, color=color)

        # ── body ───────────────────────────────────────────────────────────────
        r = hr2 + 1
        ordered = d.sort_values(["PRODUCT_CLASS", "PROD_PKG_CODE"])
        for cls, cls_rows in ordered.groupby("PRODUCT_CLASS", sort=False):
            # Class row — cost/dkg and MOH intentionally blank
            self._val(ws, r, 1, cls, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, 2, "", fill=LIGHT)
            for gi, grp in enumerate(groups):
                start = 3 + gi * NSUB
                sub = cls_rows if grp == "All" else cls_rows[cls_rows["DATABASE"] == grp]
                write_group(r, start, sub, fill=LIGHT, bold=True, show_cost=False)
            r += 1

            for pkg, pkg_rows in cls_rows.groupby("PROD_PKG_CODE", sort=False):
                # Package row — cost/dkg and MOH shown
                self._val(ws, r, 1, pkg, align="left", indent=1)
                self._val(ws, r, 2, pkg_rows["PRODUCT_NAME"].iloc[0], align="left")
                for gi, grp in enumerate(groups):
                    start = 3 + gi * NSUB
                    sub = pkg_rows if grp == "All" else pkg_rows[pkg_rows["DATABASE"] == grp]
                    write_group(r, start, sub, show_cost=True)
                ws.row_dimensions[r].outline_level = 1
                ws.row_dimensions[r].hidden = True
                r += 1

        # ── Grand total ────────────────────────────────────────────────────────
        self._val(ws, r, 1, "GRAND TOTAL", bold=True, fill=STEEL,
                  align="left", color="FFFFFF")
        self._val(ws, r, 2, "", fill=STEEL)
        for gi, grp in enumerate(groups):
            start = 3 + gi * NSUB
            sub = d if grp == "All" else d[d["DATABASE"] == grp]
            write_group(r, start, sub, fill=STEEL, bold=True,
                        color="FFFFFF", show_cost=True)

        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 26
        for gi in range(len(groups)):
            start = 3 + gi * NSUB
            for si, w in enumerate([12, 13, 15, 8]):
                ws.column_dimensions[get_column_letter(start + si)].width = w
        ws.freeze_panes = "C6"

    # ── per-entity tab (original — unchanged) ─────────────────────────────────
    def build_entity(self, entity, edf):
        ws = self.wb_inventory.create_sheet(f"{entity} Inventory"[:31])

        headers = [
            "Class / Package / Lot",  # A  col 1
            "Product Name",           # B  col 2
            "Facility",               # C  col 3
            "On-hand (kg)",           # D  col 4
            "Avg Cost/kg",            # E  col 5
            "Avg Cost/dkg",           # F  col 6
            "Extended (Local)",       # G  col 7
            "Extended (USD)",         # H  col 8
            "12M Sales (kg)",         # I  col 9
            "Months on Hand",         # J  col 10
            "Supplier",               # K  col 11
            "Lot Created",            # L  col 12
            "Expiration",             # M  col 13
            "Days Old",               # N  col 14
        ]
        ncols = len(headers)

        C_NAME    = 2
        C_FAC     = 3
        C_QTY     = 4
        C_AVG     = 5
        C_AVGD    = 6
        C_LOC     = 7
        C_USD     = 8
        C_S12     = 9
        C_MOH     = 10
        C_SUP     = 11
        C_CREATED = 12
        C_EXP     = 13
        C_DAYS    = 14

        self._title(ws,
                    f"{entity} - Inventory Detail"
                    f"   |   Generated {datetime.now():%Y-%m-%d}",
                    None, ncols)

        ws.sheet_properties.outlinePr.summaryBelow = False
        FMT_DATE = "yyyy-mm-dd"

        def fill_blanks(row, cols, fill):
            for j in cols:
                self._val(ws, row, j, "", fill=fill)

        def write_qty_velocity(row, grp, fill=None, bold=False, color=None,
                               show_moh=True):
            qty = float(grp["QTY_IN_KG"].sum())
            s12 = float(grp["SALES_12M_ALLOC"].sum())
            # MOH suppressed at class level — not meaningful across mixed products
            moh = (qty / (s12 / 12.0) if s12 > 0 else None) if show_moh else None
            self._val(ws, row, C_QTY, qty, FMT_KG,  bold=bold, fill=fill, color=color)
            self._val(ws, row, C_S12, s12, FMT_KG,  bold=bold, fill=fill, color=color)
            self._val(ws, row, C_MOH, moh, FMT_MOH, bold=bold, fill=fill, color=color)
            return qty, s12, moh

        r = 4
        self._header(ws, r, headers)
        r += 1
        first_data_row = r

        for cls, cls_rows in edf.groupby("PRODUCT_CLASS", sort=False):
            # ── Class (L0, always visible) — MOH intentionally blank ──────────
            fill_blanks(r, range(1, ncols + 1), LIGHT)
            self._val(ws, r, 1,      cls, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, C_NAME, "",  fill=LIGHT)
            self._val(ws, r, C_FAC,  "",  fill=LIGHT)
            write_qty_velocity(r, cls_rows, fill=LIGHT, bold=True, show_moh=False)
            self._val(ws, r, C_LOC, float(cls_rows["EXTENSION_PP"].sum()),
                      FMT_USD, bold=True, fill=LIGHT)
            self._val(ws, r, C_USD, float(cls_rows["EXTENSION_PP_USD"].sum()),
                      FMT_USD, bold=True, fill=LIGHT)
            r += 1

            for pkg, pkg_rows in cls_rows.groupby("PROD_PKG_CODE", sort=False):
                # ── Product-Package (L1, collapsible) — weighted avg cost ──────
                name = pkg_rows["PRODUCT_NAME"].iloc[0]

                ext_pkg  = float(pkg_rows["EXTENSION_PP_USD"].sum())
                dqty_pkg = float(pkg_rows["QTY_IN_DKG"].sum())
                qty_pkg  = float(pkg_rows["QTY_IN_KG"].sum())
                cdkg_pkg = ext_pkg / dqty_pkg if dqty_pkg else None
                cost_pkg = ext_pkg / qty_pkg  if qty_pkg  else None

                fill_blanks(r, range(1, ncols + 1), None)
                self._val(ws, r, 1,      pkg,  bold=True, align="left", indent=1)
                self._val(ws, r, C_NAME, name, bold=True, align="left")
                self._val(ws, r, C_FAC,  "")
                write_qty_velocity(r, pkg_rows, bold=True, show_moh=True)
                self._val(ws, r, C_AVG,  cost_pkg, FMT_COST, bold=True)
                self._val(ws, r, C_AVGD, cdkg_pkg, FMT_COST, bold=True)
                self._val(ws, r, C_LOC,
                          float(pkg_rows["EXTENSION_PP"].sum()),
                          FMT_USD, bold=True)
                self._val(ws, r, C_USD,
                          float(pkg_rows["EXTENSION_PP_USD"].sum()),
                          FMT_USD, bold=True)
                ws.row_dimensions[r].outline_level = 1
                r += 1

                for (fac,), fac_rows in pkg_rows.groupby(["FACILITY"], sort=False):
                    # ── Facility (L2, hidden) — WP cost ───────────────────────
                    # WP cost is pool-level (same for all lots in facility)
                    cost_wp = fac_rows["COST_KG_WP"].iloc[0]
                    cdkg_wp = fac_rows["COST_DKG_WP"].iloc[0]

                    fill_blanks(r, range(1, ncols + 1), None)
                    self._val(ws, r, 1,      pkg,  align="left", indent=2)
                    self._val(ws, r, C_NAME, name, align="left")
                    self._val(ws, r, C_FAC,  fac,  align="left")
                    write_qty_velocity(r, fac_rows, show_moh=True)
                    self._val(ws, r, C_AVG,  cost_wp, FMT_COST)
                    self._val(ws, r, C_AVGD, cdkg_wp, FMT_COST)
                    self._val(ws, r, C_LOC,
                              float(fac_rows["EXTENSION_WP"].sum()),
                              FMT_USD)
                    self._val(ws, r, C_USD,
                              float(fac_rows["EXTENSION_WP_USD"].sum()),
                              FMT_USD)
                    ws.row_dimensions[r].outline_level = 2
                    ws.row_dimensions[r].hidden = True
                    r += 1

                    for _, row in fac_rows.iterrows():
                        # ── Lot (L3, hidden) — lot-actual cost ────────────────
                        zebra = ZEBRA if r % 2 == 0 else None
                        self._val(ws, r, 1,
                                  row["LOT_CODE"] or "(no lot)",
                                  align="left", indent=3, fill=zebra)
                        self._val(ws, r, C_NAME, "",  fill=zebra)
                        self._val(ws, r, C_FAC,  fac, align="left", fill=zebra)
                        self._val(ws, r, C_QTY,  row["QTY_IN_KG"],
                                  FMT_KG,   fill=zebra)
                        self._val(ws, r, C_AVG,  row["COST_KG"],
                                  FMT_COST,  fill=zebra)
                        self._val(ws, r, C_AVGD, row["COST_DKG"],
                                  FMT_COST,  fill=zebra)
                        self._val(ws, r, C_LOC,  row["EXTENSION"],
                                  FMT_USD,   fill=zebra)
                        self._val(ws, r, C_USD,  row["EXTENSION_USD"],
                                  FMT_USD,   fill=zebra)
                        self._val(ws, r, C_SUP,  row["SUPPLIER_NAME"],
                                  align="left", fill=zebra)
                        crt = row["LOT_CREATED_DATE"]
                        self._val(ws, r, C_CREATED,
                                  None if pd.isna(crt) else crt.to_pydatetime(),
                                  FMT_DATE, align="center", fill=zebra)
                        exp = row["LOT_EXPIRATION_DATE"]
                        self._val(ws, r, C_EXP,
                                  None if pd.isna(exp) else exp.to_pydatetime(),
                                  FMT_DATE, align="center", fill=zebra)
                        self._val(ws, r, C_DAYS, row["DAYS_OLD"],
                                  FMT_KG, fill=zebra)
                        ws.row_dimensions[r].outline_level = 3
                        ws.row_dimensions[r].hidden = True
                        r += 1

        # ── Entity total ───────────────────────────────────────────────────────
        fill_blanks(r, range(1, ncols + 1), STEEL)
        self._val(ws, r, 1, f"{entity} TOTAL", bold=True, fill=STEEL,
                  align="left", color="FFFFFF")
        write_qty_velocity(r, edf, fill=STEEL, bold=True,
                           color="FFFFFF", show_moh=True)
        self._val(ws, r, C_LOC, float(edf["EXTENSION_PP"].sum()),
                  FMT_USD, bold=True, fill=STEEL, color="FFFFFF")
        self._val(ws, r, C_USD, float(edf["EXTENSION_PP_USD"].sum()),
                  FMT_USD, bold=True, fill=STEEL, color="FFFFFF")

        #          A   B   C   D   E   F   G   H   I   J   K   L   M   N
        widths = [32, 28, 12, 13, 11, 11, 15, 15, 14, 13, 22, 13, 13, 10]
        for i, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(i + 1)].width = w
        ws.freeze_panes = f"A{first_data_row}"

    # ── per-entity tab, warehouse-first drill (Facility workbook) ─────────────
    def build_entity_by_facility(self, entity, edf, wb):
        """
        Same source data as build_entity(), but re-ordered so Facility leads
        the drill instead of trailing it: Facility (L0) -> Package (L1) ->
        Lot (L2). Product Class is dropped as a drill level here (it's an
        accounting classification, not something a warehouse view needs) and
        kept only as a small context column. Lives only in the Facility
        workbook, titled "Inventory Report by Warehouse" — the inventory
        workbook's entity tabs (Class -> Package -> Facility -> Lot) are
        untouched.

        Cost basis: since Facility is now the top-level grouping, Facility
        (L0) and Package (L1, which sits directly under a fixed facility)
        use the WP basis (EXTENSION_WP / EXTENSION_WP_USD / COST_DKG_WP) —
        the cost pool that is actually specific to a (facility, product)
        combination — instead of the PP basis used in the inventory
        workbook's entity tabs. Lot (L2) is unchanged — lot-actual cost via
        COST_DKG / EXTENSION.
        """
        ws = wb.create_sheet(f"{entity} by Warehouse"[:31])

        headers = [
            "Facility / Package / Lot",  # A  col 1
            "Product Name",              # B  col 2
            "Product Class",             # C  col 3
            "On-hand (kg)",               # D  col 4
            "Avg Cost/kg",                 # E  col 5
            "Avg Cost/dkg",                # F  col 6
            "Extended (Local)",            # G  col 7
            "Extended (USD)",              # H  col 8
            "12M Sales (kg)",              # I  col 9
            "Months on Hand",              # J  col 10
            "Supplier",                    # K  col 11
            "Lot Created",                 # L  col 12
            "Expiration",                  # M  col 13
            "Days Old",                    # N  col 14
        ]
        ncols = len(headers)

        C_NAME    = 2
        C_CLASS   = 3
        C_QTY     = 4
        C_AVG     = 5
        C_AVGD    = 6
        C_LOC     = 7
        C_USD     = 8
        C_S12     = 9
        C_MOH     = 10
        C_SUP     = 11
        C_CREATED = 12
        C_EXP     = 13
        C_DAYS    = 14

        self._title(ws,
                    f"{entity} - Inventory Report by Warehouse"
                    f"   |   Generated {datetime.now():%Y-%m-%d}",
                    None, ncols)

        ws.sheet_properties.outlinePr.summaryBelow = False
        FMT_DATE = "yyyy-mm-dd"

        def fill_blanks(row, cols, fill):
            for j in cols:
                self._val(ws, row, j, "", fill=fill)

        def write_qty_velocity(row, grp, fill=None, bold=False, color=None,
                               show_moh=True):
            qty = float(grp["QTY_IN_KG"].sum())
            s12 = float(grp["SALES_12M_ALLOC"].sum())
            moh = (qty / (s12 / 12.0) if s12 > 0 else None) if show_moh else None
            self._val(ws, row, C_QTY, qty, FMT_KG,  bold=bold, fill=fill, color=color)
            self._val(ws, row, C_S12, s12, FMT_KG,  bold=bold, fill=fill, color=color)
            self._val(ws, row, C_MOH, moh, FMT_MOH, bold=bold, fill=fill, color=color)
            return qty, s12, moh

        r = 4
        self._header(ws, r, headers)
        r += 1
        first_data_row = r

        for fac, fac_rows in edf.groupby("FACILITY", sort=False):
            # ── Facility (L0, always visible) — WP basis, cost blank ──────────
            fill_blanks(r, range(1, ncols + 1), LIGHT)
            self._val(ws, r, 1,       fac, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, C_NAME,  "",  fill=LIGHT)
            self._val(ws, r, C_CLASS, "",  fill=LIGHT)
            write_qty_velocity(r, fac_rows, fill=LIGHT, bold=True, show_moh=False)
            self._val(ws, r, C_LOC, float(fac_rows["EXTENSION_WP"].sum()),
                      FMT_USD, bold=True, fill=LIGHT)
            self._val(ws, r, C_USD, float(fac_rows["EXTENSION_WP_USD"].sum()),
                      FMT_USD, bold=True, fill=LIGHT)
            r += 1

            for pkg, pkg_rows in fac_rows.groupby("PROD_PKG_CODE", sort=False):
                # ── Package within Facility (L1, collapsible) — WP cost,
                #    since Facility+Product IS the WP pool ────────────────────
                name     = pkg_rows["PRODUCT_NAME"].iloc[0]
                cls      = pkg_rows["PRODUCT_CLASS"].iloc[0]
                ext_wp   = float(pkg_rows["EXTENSION_WP_USD"].sum())
                dqty_pkg = float(pkg_rows["QTY_IN_DKG"].sum())
                qty_pkg  = float(pkg_rows["QTY_IN_KG"].sum())
                cdkg_wp  = ext_wp / dqty_pkg if dqty_pkg else None
                cost_wp  = ext_wp / qty_pkg  if qty_pkg  else None

                fill_blanks(r, range(1, ncols + 1), None)
                self._val(ws, r, 1,       pkg,  bold=True, align="left", indent=1)
                self._val(ws, r, C_NAME,  name, bold=True, align="left")
                self._val(ws, r, C_CLASS, cls,  align="left")
                write_qty_velocity(r, pkg_rows, bold=True, show_moh=True)
                self._val(ws, r, C_AVG,  cost_wp, FMT_COST, bold=True)
                self._val(ws, r, C_AVGD, cdkg_wp, FMT_COST, bold=True)
                self._val(ws, r, C_LOC,
                          float(pkg_rows["EXTENSION_WP"].sum()),
                          FMT_USD, bold=True)
                self._val(ws, r, C_USD, ext_wp, FMT_USD, bold=True)
                ws.row_dimensions[r].outline_level = 1
                r += 1

                for _, row in pkg_rows.iterrows():
                    # ── Lot (L2, hidden) — lot-actual cost ────────────────────
                    zebra = ZEBRA if r % 2 == 0 else None
                    self._val(ws, r, 1,
                              row["LOT_CODE"] or "(no lot)",
                              align="left", indent=2, fill=zebra)
                    self._val(ws, r, C_NAME,  "",   fill=zebra)
                    self._val(ws, r, C_CLASS, cls,  align="left", fill=zebra)
                    self._val(ws, r, C_QTY,  row["QTY_IN_KG"],
                              FMT_KG,   fill=zebra)
                    self._val(ws, r, C_AVG,  row["COST_KG"],
                              FMT_COST,  fill=zebra)
                    self._val(ws, r, C_AVGD, row["COST_DKG"],
                              FMT_COST,  fill=zebra)
                    self._val(ws, r, C_LOC,  row["EXTENSION"],
                              FMT_USD,   fill=zebra)
                    self._val(ws, r, C_USD,  row["EXTENSION_USD"],
                              FMT_USD,   fill=zebra)
                    self._val(ws, r, C_SUP,  row["SUPPLIER_NAME"],
                              align="left", fill=zebra)
                    crt = row["LOT_CREATED_DATE"]
                    self._val(ws, r, C_CREATED,
                              None if pd.isna(crt) else crt.to_pydatetime(),
                              FMT_DATE, align="center", fill=zebra)
                    exp = row["LOT_EXPIRATION_DATE"]
                    self._val(ws, r, C_EXP,
                              None if pd.isna(exp) else exp.to_pydatetime(),
                              FMT_DATE, align="center", fill=zebra)
                    self._val(ws, r, C_DAYS, row["DAYS_OLD"],
                              FMT_KG, fill=zebra)
                    ws.row_dimensions[r].outline_level = 2
                    ws.row_dimensions[r].hidden = True
                    r += 1

        # ── Entity total ───────────────────────────────────────────────────────
        fill_blanks(r, range(1, ncols + 1), STEEL)
        self._val(ws, r, 1, f"{entity} TOTAL", bold=True, fill=STEEL,
                  align="left", color="FFFFFF")
        write_qty_velocity(r, edf, fill=STEEL, bold=True,
                           color="FFFFFF", show_moh=True)
        self._val(ws, r, C_LOC, float(edf["EXTENSION_WP"].sum()),
                  FMT_USD, bold=True, fill=STEEL, color="FFFFFF")
        self._val(ws, r, C_USD, float(edf["EXTENSION_WP_USD"].sum()),
                  FMT_USD, bold=True, fill=STEEL, color="FFFFFF")

        #          A   B   C   D   E   F   G   H   I   J   K   L   M   N
        widths = [32, 28, 16, 13, 11, 11, 15, 15, 14, 13, 22, 13, 13, 10]
        for i, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(i + 1)].width = w
        ws.freeze_panes = f"A{first_data_row}"

    # ── EXCHANGE RATES (original — unchanged) ─────────────────────────────────
    def build_fx(self):
        ws = self.wb_inventory.create_sheet("Exchange Rates")
        self._title(ws, "Implied Conversion Rates",
                    "Derived from inventory extensions (local / USD). "
                    "Reference only - confirm against the spot-rate seeds.", 3)
        self._header(ws, 4, ["Entity", "Implied Rate (Local per USD)",
                              "Basis (rows used)"])
        r = 5
        for ent in (ENTITY_ORDER + sorted(
                set(self.df["DATABASE"]) - set(ENTITY_ORDER))):
            sub = self.df[self.df["DATABASE"] == ent]
            if sub.empty:
                continue
            usd  = float(sub["EXTENSION_USD"].sum())
            loc  = float(sub["EXTENSION"].sum())
            rate = loc / usd if usd else None
            self._val(ws, r, 1, ent, align="left")
            self._val(ws, r, 2, rate, "#,##0.0000" if rate else None,
                      align="right")
            self._val(ws, r, 3, f"{len(sub):,}", align="right")
            r += 1
        for col, w in zip("ABC", [16, 28, 18]):
            ws.column_dimensions[col].width = w

    # ── MOVEMENT (own workbook — entity detail + REMELTS summary) ─────────────
    @staticmethod
    def _period_label(yyyymm):
        s = str(int(yyyymm))
        return f"{s[:4]}-{s[4:]}" if len(s) == 6 else s

    def build_movement_entity(self, entity, mdf):
        ws = self.wb_movement.create_sheet(f"{entity} Movement"[:31])
        headers = ["Package", "Product Name", "Production", "Production (Dry Kg)",
                "Purchase", "Sales", "Transfer", "Other", "Net Change"]
        cols    = ["PRODUCTION_KG", "PRODUCTION_DKG", "PURCHASE_KG", "SALES_KG",
                "WAREHOUSE_TRANSFER_KG", "OTHER_KG", "TOTAL_NET_KG"]
        ncols   = len(headers)
        start   = self._period_label(mdf["START_PERIOD"].iloc[0])
        end     = self._period_label(mdf["END_PERIOD"].iloc[0])
        self._title(ws,
                    f"{entity} - Inventory Movement YTD (kg)"
                    f"   |   Generated {datetime.now():%Y-%m-%d}"
                    f"   |   {start} through {end}",
                    None, ncols)

        ws.sheet_properties.outlinePr.summaryBelow = False
        r = 4
        self._header(ws, r, headers)
        r += 1
        first = r

        for cls, cls_rows in mdf.groupby("PRODUCT_CLASS", sort=False):
            self._val(ws, r, 1, cls, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, 2, "", fill=LIGHT)
            for j, col in enumerate(cols, start=3):
                self._val(ws, r, j, float(cls_rows[col].sum()), FMT_MOVE,
                        bold=True, fill=LIGHT)
            r += 1
            for _, row in cls_rows.sort_values("PRODUCT_NAME").iterrows():
                zebra = ZEBRA if r % 2 == 0 else None
                self._val(ws, r, 1, row["PROD_PKG_CODE"], align="left",
                        indent=1, fill=zebra)
                self._val(ws, r, 2, row["PRODUCT_NAME"], align="left", fill=zebra)
                for j, col in enumerate(cols, start=3):
                    self._val(ws, r, j, float(row[col]), FMT_MOVE,
                            bold=(col == "TOTAL_NET_KG"), fill=zebra)
                ws.row_dimensions[r].outline_level = 1
                r += 1

        self._val(ws, r, 1, f"{entity} TOTAL", bold=True, fill=STEEL,
                align="left", color="FFFFFF")
        self._val(ws, r, 2, "", fill=STEEL)
        for j, col in enumerate(cols, start=3):
            self._val(ws, r, j, float(mdf[col].sum()), FMT_MOVE,
                    bold=True, fill=STEEL, color="FFFFFF")

        for col, w in zip("ABCDEFGHI", [22, 28, 13, 15, 13, 13, 13, 13, 14]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = f"A{first}"

    def build_movement_remelts(self, mdf):
        """
        Single tab showing YTD movement for REMELTS product class only,
        grouped by database then package — mirrors build_movement_entity
        structure but spans all entities. Lives in the movement workbook,
        as the first tab.
        """
        ws = self.wb_movement.create_sheet("REMELTS Movement", 0)

        # Filter to REMELTS only
        rdf = mdf[mdf["PRODUCT_CLASS"].str.upper() == "REMELTS"].copy()
        if rdf.empty:
            return

        headers = ["Package", "Product Name", "Production", "Production (Dry Kg)",
                "Purchase", "Sales", "Transfer", "Other", "Net Change"]
        cols    = ["PRODUCTION_KG", "PRODUCTION_DKG", "PURCHASE_KG", "SALES_KG",
                "WAREHOUSE_TRANSFER_KG", "OTHER_KG", "TOTAL_NET_KG"]
        ncols   = len(headers)
        start   = self._period_label(rdf["START_PERIOD"].iloc[0])
        end     = self._period_label(rdf["END_PERIOD"].iloc[0])
        self._title(ws,
                    f"REMELTS — Inventory Movement YTD (kg)"
                    f"   |   Generated {datetime.now():%Y-%m-%d}"
                    f"   |   {start} through {end}",
                    None, ncols)

        ws.sheet_properties.outlinePr.summaryBelow = False
        r = 4
        self._header(ws, r, headers)
        r += 1
        first = r

        # Sort databases by ENTITY_ORDER
        order   = {e: i for i, e in enumerate(ENTITY_ORDER)}
        sorted_dbs = sorted(rdf["DATABASE"].unique(),
                            key=lambda e: order.get(e, 999))

        for db in sorted_dbs:
            db_rows = rdf[rdf["DATABASE"] == db]

            # ── Database (level 0, always visible) ────────────────────────────
            self._val(ws, r, 1, db, bold=True, fill=LIGHT, align="left")
            self._val(ws, r, 2, "",  fill=LIGHT)
            for j, col in enumerate(cols, start=3):
                self._val(ws, r, j, float(db_rows[col].sum()), FMT_MOVE,
                        bold=True, fill=LIGHT)
            r += 1

            # ── Package (level 1, collapsible) ─────────────────────────────────
            for _, row in db_rows.sort_values("PRODUCT_NAME").iterrows():
                zebra = ZEBRA if r % 2 == 0 else None
                self._val(ws, r, 1, row["PROD_PKG_CODE"], align="left",
                        indent=1, fill=zebra)
                self._val(ws, r, 2, row["PRODUCT_NAME"], align="left", fill=zebra)
                for j, col in enumerate(cols, start=3):
                    self._val(ws, r, j, float(row[col]), FMT_MOVE,
                            bold=(col == "TOTAL_NET_KG"), fill=zebra)
                ws.row_dimensions[r].outline_level = 1
                r += 1

        # ── Grand total ────────────────────────────────────────────────────────
        self._val(ws, r, 1, "REMELTS TOTAL", bold=True, fill=STEEL,
                align="left", color="FFFFFF")
        self._val(ws, r, 2, "", fill=STEEL)
        for j, col in enumerate(cols, start=3):
            self._val(ws, r, j, float(rdf[col].sum()), FMT_MOVE,
                    bold=True, fill=STEEL, color="FFFFFF")

        for col, w in zip("ABCDEFGHI", [22, 28, 13, 15, 13, 13, 13, 13, 14]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = f"A{first}"

    # ── orchestration ──────────────────────────────────────────────────────────
    def build(self):
        # 1. Category pivot tab (named categories only — uncategorized excluded)
        cat_df = self.df[self.df["PRODUCT_CATEGORY"].isin(CATEGORY_ORDER)]
        if not cat_df.empty:
            self.build_category(cat_df)

        # 2. Inventory Summary
        self.build_summary()

        # 3. Entity tabs (inventory workbook — original, unchanged)
        seen_e = []
        for ent in ENTITY_ORDER + sorted(
                set(self.df["DATABASE"]) - set(ENTITY_ORDER)):
            edf = self.df[self.df["DATABASE"] == ent]
            if edf.empty or ent in seen_e:
                continue
            seen_e.append(ent)
            self.build_entity(ent, edf)

        # 4. Facility workbook — warehouse-first entity tabs only
        for ent in seen_e:
            edf = self.df[self.df["DATABASE"] == ent]
            self.build_entity_by_facility(ent, edf, wb=self.wb_facility)

        # 5. Movement workbook — REMELTS summary (first tab) + per-entity detail
        if self.move is not None and not self.move.empty:
            self.build_movement_remelts(self.move)

            seen_m = []
            for ent in ENTITY_ORDER + sorted(
                    set(self.move["DATABASE"]) - set(ENTITY_ORDER)):
                mdf = self.move[self.move["DATABASE"] == ent]
                if mdf.empty or ent in seen_m:
                    continue
                seen_m.append(ent)
                self.build_movement_entity(ent, mdf)

        # 6. FX reference (inventory workbook)
        self.build_fx()

    def save(self, inventory_path, movement_path, facility_path):
        self.wb_inventory.save(inventory_path)
        print(f"  Inventory workbook written: {inventory_path}")

        if len(self.wb_movement.sheetnames) > 0:
            self.wb_movement.save(movement_path)
            print(f"  Movement workbook written: {movement_path}")
        else:
            print("  No movement tabs to write - movement workbook skipped.")

        self.wb_facility.save(facility_path)
        print(f"  Facility workbook written: {facility_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDARD ENTRY POINT (used by report_registry.py / send_reports.py)
# ═══════════════════════════════════════════════════════════════════════════════

def build_attachments() -> list[tuple[str, bytes]]:
    """Loads data, builds the three workbooks in memory, returns
    [(filename, bytes), ...] -- this one legitimately returns MORE than one
    attachment (inventory, movement, facility), which is fine: the standard
    is 'a list of finished attachments', not 'exactly one'. Movement is
    skipped if it has no sheets (no movement data that period), matching
    ReportBuilder.save()'s own behavior."""
    import io

    loader = InventoryLoader()
    try:
        df = loader.load()
        move = loader.load_movement(df) if not df.empty else None
    finally:
        loader.close()

    if df.empty:
        print("  No on-hand rows -- nothing to report.")
        return []

    builder = ReportBuilder(df, move)
    builder.build()

    attachments: list[tuple[str, bytes]] = []

    inv_buf = io.BytesIO()
    builder.wb_inventory.save(inv_buf)
    inv_buf.seek(0)
    attachments.append((f"inventory_report_{datetime.now():%m%d%Y}.xlsx", inv_buf.getvalue()))

    if len(builder.wb_movement.sheetnames) > 0:
        move_buf = io.BytesIO()
        builder.wb_movement.save(move_buf)
        move_buf.seek(0)
        attachments.append((f"movement_report_{datetime.now():%m%d%Y}.xlsx", move_buf.getvalue()))
    else:
        print("  No movement tabs -- skipping movement attachment.")

    fac_buf = io.BytesIO()
    builder.wb_facility.save(fac_buf)
    fac_buf.seek(0)
    attachments.append((f"facility_report_{datetime.now():%m%d%Y}.xlsx", fac_buf.getvalue()))

    return attachments


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("Inventory report")
    loader = InventoryLoader()
    try:
        df   = loader.load()
        move = loader.load_movement(df) if not df.empty else None
    finally:
        loader.close()

    if df.empty:
        print("  No on-hand rows - nothing to report.")
        sys.exit(0)

    builder = ReportBuilder(df, move)
    builder.build()
    builder.save(INVENTORY_OUTPUT_PATH, MOVEMENT_OUTPUT_PATH, FACILITY_OUTPUT_PATH)
    print("Done.")


if __name__ == "__main__":
    main()