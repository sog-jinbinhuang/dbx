# Databricks notebook source
# MAGIC %md
# MAGIC ## Bronze loader - SuccessFactors dim_emp
# MAGIC The SuccessFactors export container is flat -- one file per entity,
# MAGIC always the same filename, replaced in place on each export. No
# MAGIC year/month/day/hour partitioning, no versioning to search for --
# MAGIC just read the current file directly.
# MAGIC
# MAGIC Standard comma-delimited CSV with double-quote enclosure (not the
# MAGIC \u0001-delimited format used by the CHEMPAX loader).
# MAGIC
# MAGIC All columns are STRING here on purpose -- typing/casting happens in
# MAGIC stg_successfactors_employee.sql, not here.

# COMMAND ----------
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

BASE = "abfss://raw-data-successfactor@sogstdatabricksprod01.dfs.core.windows.net"
FILE_PATH = f"{BASE}/dim_emp.csv"

dbutils.widgets.text("catalog", "prod_hr")
target_catalog = dbutils.widgets.get("catalog")

# COMMAND ----------
SCHEMA = StructType([
    StructField("Employee Id", StringType(), True),
    StructField("First Name-Personal Information", StringType(), True),
    StructField("Last Name-Personal Information", StringType(), True),
    StructField("Name-Business Unit", StringType(), True),
    StructField("Code-Business Unit", StringType(), True),
    StructField("Name-Legal Entity", StringType(), True),
    StructField("Code-Legal Entity", StringType(), True),
    StructField("Country of Registration-Legal Entity", StringType(), True),
    StructField("Name-Department", StringType(), True),
    StructField("Code-Department", StringType(), True),
    StructField("Name-Cost Center", StringType(), True),
    StructField("Code-Cost Center", StringType(), True),
    StructField("District-FOCorporateAddressDEFLT", StringType(), True),
    StructField("Country/Region-FOCorporateAddressDEFLT", StringType(), True),
    StructField("Latest Termination Date-PersonEmpTerminationInfo", StringType(), True),
    StructField("Hire Date-Employment Details", StringType(), True),
    StructField("Job Level-Position", StringType(), True),
    StructField("Job Title-Position", StringType(), True),
    StructField("label-PicklistLabel", StringType(), True),
    StructField("Supervisor-Job Information", StringType(), True),
    StructField("amount-EmpCompensationGroupSumCalculated", StringType(), True),
    StructField("Currency Code-EmpCompensationGroupSumCalculated", StringType(), True),
    StructField("Date of Salary Last Adjustment-Compensation Information", StringType(), True),
    StructField("label-PicklistLabel.1", StringType(), True),
])

# COMMAND ----------
print(f"Loading: {FILE_PATH}")

df = (spark.read
      .option("header", "true")
      .option("delimiter", ",")
      .option("quote", "\"")
      .option("multiLine", "true")   # safe default, in case any field contains embedded newlines
      .schema(SCHEMA)
      .csv(FILE_PATH))

# Delta doesn't allow spaces (or a few other characters) in column names for
# managed tables -- SuccessFactors' raw headers have literal spaces
# ("Employee Id", "First Name-Personal Information", etc.), so rename them
# here rather than enabling Delta's Column Mapping feature.
for col_name in df.columns:
    df = df.withColumnRenamed(col_name, col_name.replace(" ", "_"))

df = (df
      .withColumn("ingestion_ts", F.current_timestamp())
      .withColumn("source_file_path", F.lit(FILE_PATH)))

row_count = df.count()
if row_count == 0:
    raise Exception(f"{FILE_PATH} loaded 0 rows -- aborting write to avoid overwriting bronze with empty data.")

# COMMAND ----------
target_table = f"{target_catalog}.hr_raw.dim_emp"
df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target_table)
print(f"{target_table} written: {row_count} rows")

# COMMAND ----------
display(spark.table(target_table).limit(10))
