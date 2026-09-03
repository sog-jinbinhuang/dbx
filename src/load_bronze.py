# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC ## Bronze loader (generic)
# MAGIC Reads the LATEST hour-folder per database for a given table (current-state
# MAGIC snapshot, not history), unions all databases together, and overwrites the
# MAGIC bronze table. `catalog` and `table_name` are job parameters, so this one
# MAGIC script works for every table and every environment (dev/staging/prod).
# MAGIC
# MAGIC Schemas are loaded from src/schemas/<table>.yml (plain YAML column lists) --
# MAGIC no Python modules, no importlib.

# COMMAND ----------
import yaml
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

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
def get_schema(table_name: str) -> StructType:
    """Reads schemas/<table>.yml (a plain list of column names) and builds
    a Spark schema. All columns are STRING -- typing/casting happens later,
    in the dbt staging model, not here."""
    path = f"schemas/{table_name.lower()}.yml"
    try:
        with open(path) as f:
            columns = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise Exception(
            f"No schema file found for table '{table_name}'. "
            f"Expected src/schemas/{table_name.lower()}.yml to exist."
        ) from e
    return StructType([StructField(c, StringType(), True) for c in columns])


table_schema = get_schema(table_name)

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

# COMMAND ----------
dfs = []
for db in DATABASES:
    base_path = f"{BASE}/{db}/{table_name}/"
    latest_path = get_latest_folder_path(base_path)
    if latest_path is None:
        print(f"No data found for {db}/{table_name}, skipping")
        continue

    df = (spark.read
          .option("header", "true")
          .option("delimiter", "\u0001")   # matches Snowflake FF_CHEMPAX_CSV FIELD_DELIMITER
          .option("quote", "\"")           # matches FIELD_OPTIONALLY_ENCLOSED_BY
          .option("multiLine", "true") 
          .schema(table_schema)
          .csv(latest_path)
          .withColumn("source_database", F.lit(db.upper()))
          .withColumn("ingestion_ts", F.current_timestamp())
          .withColumn("source_file_path", F.lit(latest_path)))
    dfs.append(df)
    print(f"Loaded {db}: {df.count()} rows from {latest_path}")

# COMMAND ----------
# ---- safeguard: fail loudly instead of silently overwriting with partial data ----
MIN_DATABASES_REQUIRED = 1   # raise this once all 5 databases are reliably landing data

if len(dfs) < MIN_DATABASES_REQUIRED:
    raise Exception(
        f"Only {len(dfs)} of {len(DATABASES)} databases returned data for {table_name}. "
        f"Aborting write to avoid overwriting {target_catalog}.bronze.{table_name.lower()} with partial data."
    )

combined = dfs[0]
for d in dfs[1:]:
    combined = combined.unionByName(d)

target_table = f"{target_catalog}.bronze.{table_name.lower()}"
combined.write.mode("overwrite").saveAsTable(target_table)

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
