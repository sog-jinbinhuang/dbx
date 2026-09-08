"""
report_registry.py
===================
Single source of truth for every scheduled report. For each one:
  - which rpt_*.py module builds it
  - a "runner" function (defined below) that knows how to drive that
    specific module's actual interface and return (filename, bytes)
  - who receives it, and which schedule group it belongs to

IMPORTANT: none of the rpt_*.py files are modified. Some of them already
expose a build_report(df, orders_df, config) entry point (rpt_open_ar,
rpt_open_ap, rpt_backlog) -- their runners just call that, swapping in an
in-memory buffer for config.output_file, the same trick report_emailer.py
originally used. Others (rpt_production, rpt_sales_volume) only have a
main() with no reusable entry point, so their runners replicate main()'s
body using the module's own already-existing functions/classes -- still
zero changes to those files, just driven from here instead of `if __name__
== "__main__"`.

To add a report: write a runner (if none of the existing ones fit), add
one ReportDef. To change when something sends: change its `group`.
"""

from __future__ import annotations

import copy
import io
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# REPORTS_DIR is set by send_reports.py before this module is imported,
# resolved via the notebook context API (the one reliable source for this
# in a Databricks notebook_task -- __file__ and os.getcwd() were both tried
# and both resolved incorrectly). Falls back to cwd for any other context
# (e.g. running standalone locally) where that env var won't be set.
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", os.getcwd()))
TODAY = date.today()
_SUFFIX = TODAY.strftime("%m%d%Y")


@dataclass
class Recipients:
    to: list[str]
    cc: list[str] = field(default_factory=list)


@dataclass
class ReportDef:
    name: str
    module_path: Path
    runner: str                # key into RUNNERS below
    recipients: Recipients
    subject: str
    group: str                 # "morning" | "afternoon" | "weekly"


# ═══════════════════════════════════════════════════════════════════════════
# RUNNERS
# One per distinct report interface. Each takes the already-imported module
# and returns (filename, bytes). No rpt_*.py file is touched.
# ═══════════════════════════════════════════════════════════════════════════

def run_ar(mod) -> tuple[str, bytes]:
    """rpt_open_ar.py already exposes build_report(df, orders_df, config)
    and an AR_CONFIG instance -- just redirect its output_file to a buffer."""
    loader = mod.Loader()
    try:
        df = loader.load()
        orders_df = loader.load_new_orders()   # stub, returns None
    finally:
        loader.close()

    buf = io.BytesIO()
    config = copy.copy(mod.AR_CONFIG)   # shallow copy: never mutate the original
    config.output_file = buf
    mod.build_report(df, orders_df, config)
    buf.seek(0)
    return f"ar_report_{_SUFFIX}.xlsx", buf.getvalue()


def run_ap(mod) -> tuple[str, bytes]:
    """Same pattern as run_ar, for rpt_open_ap.py / AP_CONFIG."""
    loader = mod.Loader()
    try:
        df = loader.load()
        orders_df = loader.load_new_orders()
    finally:
        loader.close()

    buf = io.BytesIO()
    config = copy.copy(mod.AP_CONFIG)
    config.output_file = buf
    mod.build_report(df, orders_df, config)
    buf.seek(0)
    return f"ap_report_{_SUFFIX}.xlsx", buf.getvalue()


def _run_backlog(mod, config_attr: str, filename: str) -> tuple[str, bytes]:
    """Shared body for the two backlog variants (segment / rep). Note: this
    re-queries FCT_GLOBAL_BACKLOG once per variant rather than once total --
    matches per-report isolation but costs one extra warehouse query versus
    the original report_emailer.py, which loaded data once and reused it
    across both configs. Worth optimizing later if query cost matters;
    left simple for now since correctness > shaving one query."""
    loader = mod.Loader()
    try:
        df = loader.load()
        orders_df = loader.load_new_orders()
    finally:
        loader.close()

    buf = io.BytesIO()
    config = copy.copy(getattr(mod, config_attr))
    config.output_file = buf
    mod.build_report(df, orders_df, config)
    buf.seek(0)
    return filename, buf.getvalue()


def run_backlog_segment(mod) -> tuple[str, bytes]:
    return _run_backlog(mod, "SEGMENT_CONFIG",
                         f"sales_report_by_product_segment_{_SUFFIX}.xlsx")


def run_backlog_rep(mod) -> tuple[str, bytes]:
    return _run_backlog(mod, "REP_CONFIG",
                         f"sales_report_by_sales_rep_{_SUFFIX}.xlsx")


def run_production(mod) -> tuple[str, bytes]:
    """rpt_production.py has no build_report()/config split -- this
    replicates main()'s body exactly, calling the module's own
    build_entity_tab() per entity, just writing to a buffer instead of
    OUTPUT_FILE."""
    from openpyxl import Workbook

    loader = mod.Loader()
    try:
        vc_df = loader.load_volume_cost()
        opex_df = loader.load_opex()
    finally:
        loader.close()

    wb = Workbook()
    wb.remove(wb.active)
    for entity in mod.ENTITIES:
        mod.build_entity_tab(wb, entity, vc_df, opex_df)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return f"production_report_{_SUFFIX}.xlsx", buf.getvalue()


def run_sales_volume(mod) -> tuple[str, bytes]:
    """rpt_sales_volume.py also has no build_report()/config split -- this
    replicates main()'s body, reusing the module's own pivot/write
    functions unchanged."""
    from openpyxl import Workbook

    loader = mod.Loader()
    try:
        df = loader.load()
    finally:
        loader.close()

    months = mod.build_month_index()
    actual_all = mod.build_product_pivot(df[~df["_IS_OPEN"]], months)
    open_all = mod.build_product_pivot(df[df["_IS_OPEN"]], None)
    summary_df = mod.build_summary(actual_all, open_all)
    open_periods_all = (
        [c for c in open_all.columns if c != "_TOTAL"] if not open_all.empty else []
    )

    wb = Workbook()
    wb.remove(wb.active)
    mod.write_summary_tab(wb, summary_df, months, open_periods_all)

    databases = sorted(d for d in df["DATABASE"].unique() if d)
    for db in databases:
        db_df = df[df["DATABASE"] == db]

        actual_detail = mod.build_detail_pivot(db_df[~db_df["_IS_OPEN"]], months)
        mod.write_detail_tab(
            wb, mod.safe_sheet_name(db, " ACTUAL"),
            f"{db} \u2014 Actual Volume by Product  |  {mod.TODAY.strftime('%B %d, %Y')}",
            f"Shipped/booked volume in kg by product & customer, "
            f"{mod.period_label(months[0])} - {mod.period_label(months[-1])}",
            actual_detail,
        )

        open_detail = mod.build_detail_pivot(db_df[db_df["_IS_OPEN"]], None)
        open_periods_db = (
            [c for c in open_detail.columns if c != "_TOTAL"] if not open_detail.empty else []
        )
        open_subtitle = "Not-yet-shipped order volume in kg by product & customer"
        if open_periods_db:
            open_subtitle += (
                f", {mod.period_label(open_periods_db[0])} - "
                f"{mod.period_label(open_periods_db[-1])}"
            )
        mod.write_detail_tab(
            wb, mod.safe_sheet_name(db, " OPEN"),
            f"{db} \u2014 Open Orders by Product  |  {mod.TODAY.strftime('%B %d, %Y')}",
            open_subtitle,
            open_detail,
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return f"production_volume_report_{_SUFFIX}.xlsx", buf.getvalue()


RUNNERS = {
    "run_ar": run_ar,
    "run_ap": run_ap,
    "run_backlog_segment": run_backlog_segment,
    "run_backlog_rep": run_backlog_rep,
    "run_production": run_production,
    "run_sales_volume": run_sales_volume,
}


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

REPORT_REGISTRY: list[ReportDef] = [
    ReportDef(
        name="Open AR Aging",
        module_path=REPORTS_DIR / "rpt_open_ar.py",
        runner="run_ar",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Open AR Aging",
        group="morning",
    ),
    ReportDef(
        name="Open AP Aging",
        module_path=REPORTS_DIR / "rpt_open_ap.py",
        runner="run_ap",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Open AP Aging",
        group="morning",
    ),
    ReportDef(
        name="Backlog by Product Segment",
        module_path=REPORTS_DIR / "rpt_backlog.py",
        runner="run_backlog_segment",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Backlog Reports",
        group="afternoon",
    ),
    ReportDef(
        name="Backlog by Sales Rep",
        module_path=REPORTS_DIR / "rpt_backlog.py",
        runner="run_backlog_rep",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Backlog Reports",
        group="afternoon",
    ),
    ReportDef(
        name="Sales Volume",
        module_path=REPORTS_DIR / "rpt_sales_volume.py",
        runner="run_sales_volume",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Sales Volume",
        group="afternoon",
    ),
    ReportDef(
        name="Production Volume & Cost",
        module_path=REPORTS_DIR / "rpt_production.py",
        runner="run_production",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Production Volume & Cost",
        group="weekly",
    ),
]