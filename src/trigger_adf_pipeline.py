# Databricks notebook source
# MAGIC %md
# MAGIC ## Trigger ADF pipeline (old tenant) and wait for completion
# MAGIC Runs PL_9AM_REFRESH_SOG in the old tenant's Data Factory (mafcodatafactory)
# MAGIC via the ADF REST API, then polls until it finishes. Raises an exception
# MAGIC on failure/timeout so downstream bronze/dbt tasks don't run against
# MAGIC incomplete data.
# MAGIC
# MAGIC Auth: AAD OAuth client-credentials grant against the OLD tenant, using a
# MAGIC service principal with Data Factory Contributor (or similar) rights on
# MAGIC mafcodatafactory. Cross-tenant is fine here -- unlike storage managed
# MAGIC identities, an AAD app registration + client secret works from anywhere,
# MAGIC regardless of which tenant the caller (this notebook) runs in.

# COMMAND ----------
import time
import requests

# ---- old tenant / ADF specifics ----
OLD_TENANT_ID     = "45edc8dd-93d4-4dc1-94e2-c01bd13adbed"
SUBSCRIPTION_ID   = "bb89f8cd-abde-4cb2-bcf4-d23273a74a85"
RESOURCE_GROUP    = "rg-mafco-data"
FACTORY_NAME      = "mafcodatafactory"
PIPELINE_NAME     = "PL_9AM_REFRESH_SOG"

POLL_INTERVAL_SEC = 30
TIMEOUT_MIN       = 60   # give up waiting after this long

# ---- credentials, pulled from a Databricks secret scope (never hardcode) ----
CLIENT_ID     = dbutils.secrets.get(scope="adf-trigger", key="client-id")
CLIENT_SECRET = dbutils.secrets.get(scope="adf-trigger", key="client-secret")

# COMMAND ----------
def get_arm_token() -> str:
    """OAuth client-credentials grant against the OLD tenant, scoped to the
    Azure management API (management.azure.com), which is what the ADF
    REST API sits behind."""
    url = f"https://login.microsoftonline.com/{OLD_TENANT_ID}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://management.azure.com/.default",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

# COMMAND ----------
def trigger_pipeline(token: str) -> str:
    """Starts a run of PIPELINE_NAME, returns the runId."""
    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.DataFactory/factories/{FACTORY_NAME}"
        f"/pipelines/{PIPELINE_NAME}/createRun"
        f"?api-version=2018-06-01"
    )
    resp = requests.post(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    run_id = resp.json()["runId"]
    print(f"Triggered {PIPELINE_NAME}, runId = {run_id}")
    return run_id

# COMMAND ----------
def poll_run(token: str, run_id: str) -> str:
    """Polls the pipeline run status until it's in a terminal state or
    TIMEOUT_MIN is exceeded. Returns the final status string."""
    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.DataFactory/factories/{FACTORY_NAME}"
        f"/pipelineruns/{run_id}"
        f"?api-version=2018-06-01"
    )
    terminal_states = {"Succeeded", "Failed", "Cancelled"}
    deadline = time.time() + TIMEOUT_MIN * 60

    while True:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        status = resp.json()["status"]
        print(f"  status: {status}")

        if status in terminal_states:
            return status

        if time.time() > deadline:
            raise Exception(
                f"ADF pipeline {PIPELINE_NAME} (runId={run_id}) did not finish "
                f"within {TIMEOUT_MIN} minutes -- aborting downstream tasks."
            )

        time.sleep(POLL_INTERVAL_SEC)

# COMMAND ----------
token = get_arm_token()
run_id = trigger_pipeline(token)
final_status = poll_run(token, run_id)

if final_status != "Succeeded":
    raise Exception(
        f"ADF pipeline {PIPELINE_NAME} (runId={run_id}) finished with status "
        f"'{final_status}' -- aborting downstream bronze/dbt tasks."
    )

print(f"{PIPELINE_NAME} completed successfully (runId={run_id})")
