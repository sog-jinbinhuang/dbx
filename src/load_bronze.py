# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC ## Bronze loader (generic)
# MAGIC Reads the LATEST hour-folder per database for a given table (current-state
# MAGIC snapshot, not history), unions all databases together, and overwrites the
# MAGIC bronze table. `catalog` and `table_name` are job parameters, so this one
# MAGIC script works for every table and every environment (dev/staging/prod).
# MAGIC
# MAGIC Columns are read BY NAME from each file's own header row -- not from a
# MAGIC fixed positional schema. A shared positional schema silently corrupted
# MAGIC every column after the point where one database's export layout diverged
# MAGIC from the others (found via CHILE/APINVHDR missing a Voucher-NumberCV
# MAGIC column that the other four databases' exports include -- every
# MAGIC subsequent field was shifted by one position with no error, since bronze
# MAGIC is all-STRING and TRY_CAST()s downstream just silently returned NULL).
# MAGIC Reading by header name and using unionByName(allowMissingColumns=True)
# MAGIC means a database missing a column just gets NULL there, instead of every
# MAGIC column after it being mislabeled.

# COMMAND ----------
from pyspark.sql import functions as F

# ---- parameters (come from the Databricks Job / bundle, not hardcoded) ----
dbutils.widgets.text("catalog", "dev")           # bundle variable: dev / staging / prod
dbutils.widgets.text("table_name", "PRODUCT")    # e.g. PRODUCT, APINVHDR, ...

target_catalog = dbutils.widgets.get("catalog")
table_name = dbutils.widgets.get("table_name")

DATABASES = ["CHILE", "China", "EVD", "US", "Weifeng"]
# Updated for new tenant: storage account is sogstdatabricksprod01 (per the
# external location ext-loc-raw-data), container name (raw-data) unchanged.
BASE = "abfss://raw-data@sogstdatabricksprod01.dfs.core.windows.net"

# COMMAND ----------
def get_latest_folder_path(base_path):
    """Walks year/month/day/hour and returns the path to the most recent hour folder."""
    def latest_subfolder(path):
        try:
            items = [f.name.rstrip("/") for f in dbutils.fs.ls(path) if f.isDir()]
        except Exception as e:
            print(f"  (could not list {path}: {e})")
            return None
        return max(items) if items else None

    year = latest_subfolder(base_path)
    if not year:
        return None
    month = latest_subfolder(f"{base_path}{year}/")
    if not month:
        return None
    day = latest_subfolder(f"{base_path}{year}/{month}/")
    if not day:
        return None
    hour = latest_subfolder(f"{base_path}{year}/{month}/{day}/")
    if not hour:
        return None

    return f"{base_path}{year}/{month}/{day}/{hour}/"


def get_latest_file_path(hour_folder_path):
    """Within the resolved hour-folder, returns the path to the single most
    recent file, not the whole folder. Filenames embed a full timestamp
    (e.g. APINVHDR_20260905_125730.csv), so a plain lexicographic sort picks
    the right one.

    This matters because ADF drops a FULL snapshot per run, not an
    incremental delta -- if the refresh job is triggered more than once
    within the same hour (manual re-runs during testing, or two scheduled
    runs landing in the same hour), the folder ends up with multiple
    full-snapshot files. Reading the whole folder (the old behavior) unions
    all of them together, silently multiplying row counts. Reading only the
    latest file avoids that regardless of how many stale files accumulate
    in the folder."""
    try:
        files = [f.path for f in dbutils.fs.ls(hour_folder_path)
                 if not f.isDir() and f.name.lower().endswith(".csv")]
    except Exception as e:
        print(f"  (could not list {hour_folder_path}: {e})")
        return None
    return max(files) if files else None

# COMMAND ----------
dfs = []
for db in DATABASES:
    base_path = f"{BASE}/{db}/{table_name}/"
    hour_folder = get_latest_folder_path(base_path)
    if hour_folder is None:
        print(f"No data found for {db}/{table_name}, skipping")
        continue

    latest_path = get_latest_file_path(hour_folder)
    if latest_path is None:
        print(f"No files found in {hour_folder} for {db}/{table_name}, skipping")
        continue

    # No .schema() here on purpose -- columns are named from each file's own
    # header row, so a database whose export has a different column layout
    # (missing/extra/reordered field) doesn't silently corrupt everything
    # after the divergence point. Without an explicit schema or
    # inferSchema=true, Spark defaults every column to STRING, which is the
    # same all-string behavior the old fixed schema was providing anyway --
    # typing/casting still happens later, in the dbt staging models.
    df = (spark.read
          .option("header", "true")
          .option("delimiter", "\u0001")   # matches Snowflake FF_CHEMPAX_CSV FIELD_DELIMITER
          .option("quote", "\"")           # matches FIELD_OPTIONALLY_ENCLOSED_BY
          .option("multiLine", "true") 
          .csv(latest_path)
          .withColumn("source_database", F.lit(db.upper()))
          .withColumn("ingestion_ts", F.current_timestamp())
          .withColumn("source_file_path", F.lit(latest_path)))
    dfs.append(df)
    print(f"Loaded {db}: {df.count()} rows, {len(df.columns)} columns, from {latest_path}")

# COMMAND ----------
# ---- safeguard: fail loudly instead of silently overwriting with partial data ----
MIN_DATABASES_REQUIRED = 1   # raise this once all 5 databases are reliably landing data

if len(dfs) < MIN_DATABASES_REQUIRED:
    raise Exception(
        f"Only {len(dfs)} of {len(DATABASES)} databases returned data for {table_name}. "
        f"Aborting write to avoid overwriting {target_catalog}.bronze.{table_name.lower()} with partial data."
    )

# ---- flag any column-set mismatch across databases, don't just paper over it ----
all_columns = [set(d.columns) for d in dfs]
common = set.intersection(*all_columns)
union_all_cols = set.union(*all_columns)
if union_all_cols != common:
    for db, d in zip(DATABASES, dfs):
        extra = set(d.columns) - common
        missing = union_all_cols - set(d.columns)
        if extra or missing:
            print(f"  COLUMN MISMATCH for {db}: extra={sorted(extra)}  missing={sorted(missing)}")

combined = dfs[0]
for d in dfs[1:]:
    # allowMissingColumns: a database whose export lacks a column that
    # others have gets NULL there instead of every subsequent column being
    # silently mislabeled (the root cause of the CHILE/APINVHDR issue).
    combined = combined.unionByName(d, allowMissingColumns=True)

target_table = f"{target_catalog}.bronze.{table_name.lower()}"
combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target_table)

total_rows = combined.count()
print(f"{target_table} written: {total_rows} total rows")

# COMMAND ----------
# ---- verification: row counts per database ----
display(
    spark.table(target_table)
         .groupBy("source_database")
         .count()
         .orderBy("source_database")
)