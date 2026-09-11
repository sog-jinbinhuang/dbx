"""
report_registry.py
===================
Single source of truth for every scheduled report: which module builds it,
who receives it, and which schedule group (morning / afternoon / weekly) it
belongs to.

Every rpt_*.py file exposes ONE standard function:

    def build_attachments() -> list[tuple[str, bytes]]:
        ...

That's the only contract this registry relies on. Internally each file can
do whatever it needs (a Loader class, a build_report(df, config) split, a
multi-workbook ReportBuilder, whatever) -- none of that leaks into this
file anymore. Most reports return a single-item list; a couple (e.g.
Global Inventory) legitimately return more than one attachment.

To add a report: write build_attachments() in the new rpt_*.py file (using
whatever internal structure makes sense), add one ReportDef here. To change
when something sends: change its `group`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# REPORTS_DIR is set by send_reports.py before this module is imported,
# resolved via the notebook context API (the one reliable source for this
# in a Databricks notebook_task -- __file__ and os.getcwd() were both tried
# and both resolved incorrectly). Falls back to cwd for any other context
# (e.g. running standalone locally) where that env var won't be set.
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", os.getcwd()))


@dataclass
class Recipients:
    to: list[str]
    cc: list[str] = field(default_factory=list)


@dataclass
class ReportDef:
    name: str
    module_path: Path
    recipients: Recipients
    subject: str
    group: str                 # "morning" | "afternoon" | "weekly"


REPORT_REGISTRY: list[ReportDef] = [
    ReportDef(
        name="Open AR Aging",
        module_path=REPORTS_DIR / "rpt_open_ar.py",
        recipients=Recipients(
            to=[
            "ahaque@mafcolicorice.com",
            "pberg@mafcolicorice.com",
            "rkhan@mafcolicorice.com",
            "mji@mafco-china.com",
            "emilie.alem@evd.fr",
            "mcampbell@mafcolicorice.com",
            "qgao@mafco-china.com",
            "jhuang@mafcolicorice.com",],
        ),
        subject="Open AR Aging",
        group="morning",
    ),
    ReportDef(
        name="Open AP Aging",
        module_path=REPORTS_DIR / "rpt_open_ap.py",
        recipients=Recipients(
            to=[
                "ahaque@mafcolicorice.com",
                "pberg@mafcolicorice.com",
                "rkhan@mafcolicorice.com",
                "mji@mafco-china.com",
                "emilie.alem@evd.fr",
                "dmoore@mafcolicorice.com",
                "qgao@mafco-china.com",
                "jhuang@mafcolicorice.com",],
        ),
        subject="Open AP Aging",
        group="morning",
    ),
    ReportDef(
        name="Global Inventory",
        module_path=REPORTS_DIR / "rpt_inventory.py",
        recipients=Recipients(
            to=[        
                "lcollison@mafcolicorice.com",
                "ahaque@mafcolicorice.com",
                "pberg@mafcolicorice.com",
                "rkhan@mafcolicorice.com",
                "showl@mafco-china.com",
                "lergasheva@mafcolicorice.com",
                "sandra.amouzegh@evd.fr",
                "emilie.alem@evd.fr",
                "nicolas.raspail@evd.fr",
                "gaetan.baldy@evd.fr",
                "jf.panuel@evd.fr",
                "caroline.bidart@evd.fr",
                "jhuang@mafcolicorice.com",],
        ),
        subject="Global Inventory",
        group="morning",
    ),
    ReportDef(
        name="Backlog Reports",
        module_path=REPORTS_DIR / "rpt_backlog.py",
        recipients=Recipients(
            to=[
                "jsrobinson@mafcolicorice.com",
                "lcollison@mafcolicorice.com",
                "ahaque@mafcolicorice.com",
                "mlima@mafcolicorice.com",
                "djames@mafcolicorice.com",
                "kmehmood@mafcolicorice.com",
                "kanda.wanichkanjanakul@wholeearthbrands.com",
                "schauhan@mafcolicorice.com",
                "gwenn.boie@evd.fr",
                "jhe@mafco-china.com",
                "lynns@mafco-china.com",
                "florian.mauny@evd.fr",
                "arobinson@mafcolicorice.com",
                "lergasheva@mafcolicorice.com",
                "jhuang@mafcolicorice.com",],
        ),
        subject="Backlog Reports",
        group="afternoon",
    ),
    ReportDef(
        name="Sales Volume",
        module_path=REPORTS_DIR / "rpt_sales_volume.py",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Sales Volume",
        group="weekly",
    ),
    ReportDef(
        name="Production Volume & Cost",
        module_path=REPORTS_DIR / "rpt_production.py",
        recipients=Recipients(
            to=["jhuang@mafcolicorice.com"],
        ),
        subject="Production Volume & Cost",
        group="weekly",
    ),
    ReportDef(
    name="Backlog Reports (China)",
    module_path=REPORTS_DIR / "rpt_backlog_china.py",
    recipients=Recipients(to=["showl@mafco-china.com","jhe@mafco-china.com","jhuang@mafcolicorice.com",]),
    subject="Backlog Reports — China / Weifeng",
    group="afternoon",  # matches the original report_groups.py grouping
    ),
]
