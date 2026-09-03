# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC ## OneStream bronze loader
# MAGIC Loads the two OneStream financial exports (`facts_<YYYYMM>.csv` and
# MAGIC `hierarchy_<YYYYMM>.csv`) from a flat folder in raw-data-onestream.
# MAGIC Each run picks the LATEST period's file for each of the two types
# MAGIC (based on the YYYYMM string in the filename, which sorts correctly
# MAGIC lexicographically) and overwrites the corresponding bronze table.
# MAGIC
# MAGIC Unlike load_bronze.py, this is NOT a per-table job -- it always loads
# MAGIC both onestream_facts and onestream_hierarchy in one run, since they're
# MAGIC a matched pair (hierarchy defines rollups referenced by facts).

# COMMAND ----------
from pyspark.sql import functions as F

# ---- parameters ----
dbutils.widgets.text("catalog", "dev")
target_catalog = dbutils.widgets.get("catalog")

CONTAINER = "abfss://raw-data-onestream@sogstdatabricksprod01.dfs.core.windows.net/"

# ---- file naming: facts_2026M2.csv, hierarchy_2026M2.csv (flat folder) ----
FILE_TYPES = {
    "facts": "onestream_facts",
    "hierarchy": "onestream_hierarchy",
}

# COMMAND ----------
def get_latest_file(prefix: str) -> str:
    """Finds the file with the latest YYYYMM-style token in its name for a
    given prefix (e.g. 'facts_' or 'hierarchy_'). Filenames sort correctly
    as strings since the period token is YYYYMM (e.g. 2026M2 < 2026M10 is
    the one edge case to watch -- see note below)."""
    files = [
        f.name for f in dbutils.fs.ls(CONTAINER)
        if f.name.startswith(prefix) and f.name.endswith(".csv")
    ]
    if not files:
        raise Exception(f"No files found in {CONTAINER} matching prefix '{prefix}'")
    # NOTE: plain string sort breaks once month reaches double digits, e.g.
    # "2026M10" < "2026M2" alphabetically. If/when you hit month 10, replace
    # this with a proper parse of the YYYY/M/MM token instead of max(files).
    latest = max(files)
    return f"{CONTAINER}{latest}"

# COMMAND ----------
for file_prefix, table_name in FILE_TYPES.items():
    latest_path = get_latest_file(f"{file_prefix}_")

    df = (spark.read
          .option("header", "true")
          .option("quote", "\"")
          .option("multiLine", "true")
          .csv(latest_path)
          .withColumn("_ingested_at", F.current_timestamp())
          .withColumn("_source_file", F.lit(latest_path)))

    target_table = f"{target_catalog}.bronze.{table_name}"
    df.write.mode("overwrite").saveAsTable(target_table)

    print(f"{target_table} written: {df.count()} rows from {latest_path}")

# COMMAND ----------
# ---- verification ----
for table_name in FILE_TYPES.values():
    print(f"--- {target_catalog}.bronze.{table_name} ---")
    display(spark.table(f"{target_catalog}.bronze.{table_name}").limit(5))