# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC ## OneStream bronze loader
# MAGIC Loads the three OneStream financial exports from a flat folder in
# MAGIC raw-data-onestream:
# MAGIC   - `facts_<YYYYMM>.csv`  -- PERIOD-SCOPED and ACCUMULATING: a new file
# MAGIC     lands each month (facts_2026M1.csv, facts_2026M2.csv, ...). Every run
# MAGIC     reads ALL matching files and rebuilds the bronze table as their union --
# MAGIC     NOT just the latest one. This matters: fct_income_statement's
# MAGIC     period-over-period delta (LAG across time_period) only works when more
# MAGIC     than one period is actually present in the table at once.
# MAGIC   - `hierarchy.csv`       -- STATIC filename, no period token. OneStream's
# MAGIC     chart of accounts / entity tree is a current-state snapshot, not
# MAGIC     something that gets a new dated file each month.
# MAGIC   - `fxrates.csv`         -- STATIC filename, no period token. Each export
# MAGIC     already contains its full period range (60+ periods in one file).
# MAGIC
# MAGIC Re-running this is safe and idempotent: it always rebuilds each bronze
# MAGIC table fresh from whatever's currently in the container, rather than
# MAGIC appending -- so a corrected re-export under the same filename is picked
# MAGIC up automatically, and running twice in a row never creates duplicate rows.
# MAGIC (If a correction ever needs a NEW filename instead of overwriting the old
# MAGIC one, delete the superseded file from the container first -- this loader
# MAGIC has no way to know two files represent the same, now-stale period.)
# MAGIC
# MAGIC Unlike load_bronze.py, this is NOT a per-table job -- it always loads all
# MAGIC three in one run, since they're a matched set (hierarchy defines rollups
# MAGIC referenced by facts; fxrates supports translating facts posted in a
# MAGIC local, non-USD currency).

# COMMAND ----------
from functools import reduce
from pyspark.sql import functions as F

# ---- parameters ----
dbutils.widgets.text("catalog", "dev")
target_catalog = dbutils.widgets.get("catalog")

CONTAINER = "abfss://raw-data-onestream@sogstdatabricksprod01.dfs.core.windows.net/"

# ---- file config: mix of accumulating (facts) and static-filename (hierarchy, fxrates) ----
FILE_TYPES = {
    "facts": {
        "table": "onestream_facts",
        "period_scoped": True,
        "prefix": "facts_",
    },
    "hierarchy": {
        "table": "onestream_hierarchy",
        "period_scoped": False,
        "filename": "hierarchy.csv",
    },
    "fxrates": {
        "table": "onestream_fxrates",
        "period_scoped": False,
        "filename": "fxrates.csv",
    },
}

# COMMAND ----------
def get_all_period_files(prefix: str) -> list:
    """Returns every file matching the given prefix (e.g. 'facts_'), not just
    the latest -- period-scoped data needs to ACCUMULATE across periods, not
    be replaced by whichever file happens to sort last."""
    files = [
        f.name for f in dbutils.fs.ls(CONTAINER)
        if f.name.startswith(prefix) and f.name.endswith(".csv")
    ]
    if not files:
        raise Exception(f"No files found in {CONTAINER} matching prefix '{prefix}'")
    return sorted(files)


def get_static_file(filename: str) -> str:
    """Returns the path to a fixed-name file (no period token), after
    confirming it actually exists in the container -- fails loudly rather
    than silently reading nothing if the filename or path is wrong."""
    existing = {f.name for f in dbutils.fs.ls(CONTAINER)}
    if filename not in existing:
        raise Exception(f"'{filename}' not found in {CONTAINER}. Files present: {sorted(existing)}")
    return f"{CONTAINER}{filename}"


def read_csv(path: str):
    return (spark.read
            .option("header", "true")
            .option("quote", "\"")
            .option("multiLine", "true")
            .csv(path)
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.lit(path)))

# COMMAND ----------
for file_key, config in FILE_TYPES.items():
    if config["period_scoped"]:
        filenames = get_all_period_files(config["prefix"])
        dfs = [read_csv(f"{CONTAINER}{fn}") for fn in filenames]
        df = reduce(lambda a, b: a.unionByName(b), dfs)
        source_desc = f"{len(filenames)} files ({', '.join(filenames)})"
    else:
        source_path = get_static_file(config["filename"])
        df = read_csv(source_path)
        source_desc = source_path

    target_table = f"{target_catalog}.bronze.{config['table']}"
    df.write.mode("overwrite").saveAsTable(target_table)

    print(f"{target_table} written: {df.count()} rows from {source_desc}")

# COMMAND ----------
# ---- verification ----
for config in FILE_TYPES.values():
    print(f"--- {target_catalog}.bronze.{config['table']} ---")
    display(spark.table(f"{target_catalog}.bronze.{config['table']}").limit(5))
    if config["period_scoped"]:
        print("Distinct time periods loaded:")
        display(spark.table(f"{target_catalog}.bronze.{config['table']}").select("TimePeriod").distinct())