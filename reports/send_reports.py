# Databricks notebook source
# MAGIC %md
# MAGIC ## send_reports
# MAGIC Generic report sender. Takes a `frequency_group` job parameter
# MAGIC (morning / afternoon / weekly) and sends every report in
# MAGIC report_registry.py tagged with that group.
# MAGIC
# MAGIC Replaces the old per-frequency emailer scripts (report_emailer.py,
# MAGIC finance_emailer.py, weekly_emailer.py, inventory_emailer.py) -- one
# MAGIC generic notebook + a central registry instead of one script per group.
# MAGIC
# MAGIC All three frequency groups are now chained as the final task of their
# MAGIC own dedicated pipeline (daily_full_refresh_morning / _afternoon /
# MAGIC _weekly), so freshness is guaranteed by task dependency -- this
# MAGIC notebook doesn't need to independently check whether upstream data is
# MAGIC current.
# MAGIC
# MAGIC To change what sends when: edit report_registry.py, not this file or
# MAGIC the job YAMLs.

# COMMAND ----------
import importlib.util
import os
import smtplib
import sys
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# COMMAND ----------
# Resolve this notebook's own directory via the notebook context API --
# neither __file__ nor os.getcwd() reliably reflect the real workspace file
# path for a .py file executed as a Databricks notebook (both were tried and
# both resolved incorrectly). notebookPath() comes straight from the job's
# own metadata instead of Python-level inference, so it's the one source
# that's actually reliable here. Must run BEFORE importing report_registry,
# since that's when REPORTS_DIR gets computed.
_notebook_path = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    .notebookPath().get()
)
_reports_dir = "/Workspace" + os.path.dirname(_notebook_path)
os.environ["REPORTS_DIR"] = _reports_dir
print(f"Resolved REPORTS_DIR = {_reports_dir}")

# COMMAND ----------
from report_registry import REPORT_REGISTRY, ReportDef

# COMMAND ----------
dbutils.widgets.text("frequency_group", "morning")
FREQUENCY_GROUP = dbutils.widgets.get("frequency_group")

dbutils.widgets.text("warehouse_id", "a702d1b52888138c")   # sql-wh-analytics-prod-01
WAREHOUSE_ID = dbutils.widgets.get("warehouse_id")

# Each rpt_*.py file reads DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH /
# DATABRICKS_TOKEN from os.environ at import time (module-level code, meant
# for running the script standalone from a terminal with those set by hand).
# A job cluster has none of these set automatically, so we populate them here
# -- before any rpt_*.py file gets imported -- using the notebook's own
# execution context. The context token is short-lived and scoped to this
# run's permissions, so no extra secret needs to be stored just for this.
os.environ["DATABRICKS_SERVER_HOSTNAME"] = spark.conf.get("spark.databricks.workspaceUrl")
os.environ["DATABRICKS_HTTP_PATH"] = f"/sql/1.0/warehouses/{WAREHOUSE_ID}"
os.environ["DATABRICKS_TOKEN"] = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
)

SMTP_HOST     = "smtp.azurecomm.net"
SMTP_PORT     = 587
SMTP_USER     = "messaging@sweetoakgroup.com"
EMAIL_FROM    = "messaging@sweetoakgroup.com"
# SMTP password now comes from a Databricks secret, not a local env var
SMTP_PASSWORD = dbutils.secrets.get(scope="reports", key="smtp-password")
TODAY         = date.today()

# COMMAND ----------
_module_cache: dict[Path, object] = {}

def load_module(path: Path):
    """Dynamically imports a rpt_*.py file, same technique the old emailer
    scripts used, cached so a module used by multiple registry entries
    (unlikely here, but matches old behavior) isn't re-imported."""
    if path in _module_cache:
        return _module_cache[path]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    # Must register in sys.modules BEFORE exec_module -- some rpt_*.py files
    # use @dataclass with `from __future__ import annotations` (string type
    # hints), and dataclass's annotation resolution looks the module up via
    # sys.modules[cls.__module__] while the module is still executing. Skip
    # this and it crashes with "'NoneType' object has no attribute '__dict__'"
    # deep inside the dataclasses stdlib module.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _module_cache[path] = mod
    return mod

# COMMAND ----------
def send_email(rd: ReportDef, attachments: list[tuple[str, bytes]]) -> None:
    if not rd.recipients.to:
        print(f"  WARNING: no recipients for '{rd.name}', skipping send.")
        return
    if not attachments:
        print(f"  WARNING: no attachments built for '{rd.name}', skipping send.")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(rd.recipients.to)
    if rd.recipients.cc:
        msg["Cc"] = ", ".join(rd.recipients.cc)
    msg["Subject"] = f"{rd.subject}  |  {TODAY.strftime('%d %B %Y')}"

    body_lines = ["Attached files:"]
    for filename, data in attachments:
        part = MIMEBase("application",
                         "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)
        body_lines.append(f"  - {filename}  ({len(data) / 1024:.1f} KB)")
    msg.attach(MIMEText("\n".join(body_lines), "plain"))

    all_recipients = rd.recipients.to + rd.recipients.cc
    print(f"  Sending '{rd.name}' to {all_recipients} ...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo(); server.starttls(); server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())
    print(f"  Sent -- {len(attachments)} attachment(s).")

# COMMAND ----------
matching = [rd for rd in REPORT_REGISTRY if rd.group == FREQUENCY_GROUP]
print(f"Frequency group: {FREQUENCY_GROUP}  ({len(matching)} report(s))")

if not matching:
    print("  No reports registered for this group -- nothing to do.")

for rd in matching:
    print(f"\nBuilding: {rd.name}  ({rd.module_path.name})")
    mod = load_module(rd.module_path)

    # Every rpt_*.py exposes this one standard function -- the registry no
    # longer needs to know each report's internal structure at all.
    attachments = mod.build_attachments()
    for filename, data in attachments:
        print(f"  Built {filename}  ({len(data) / 1024:.1f} KB)")

    send_email(rd, attachments)

print("\nDone.")