# Databricks notebook source
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

# COMMAND ----------

dbutils.widgets.text('Datasource_name', '', label='Datasource Name')
dbutils.widgets.text('raw_config_path', '', label='raw_config_path')
dbutils.widgets.text('bronze_config_path', '', label='bronze_config_path')
dbutils.widgets.text('env', '', label='Enviornment variable')
Datasource_name = dbutils.widgets.get("Datasource_name")
raw_config_path = dbutils.widgets.get("raw_config_path")
bronze_config_path = dbutils.widgets.get("bronze_config_path")
env = dbutils.widgets.get("env") 

# COMMAND ----------

# Initialize Databricks SDK client
w = WorkspaceClient()

# Define job details
JOB_ID = 194247849639410
new_name = f"{Datasource_name} - dnap ingestion generic workflow"

# Dynamic parameters to pass
dynamic_params = {
    "datasource_name": Datasource_name,
    "configuration_path": raw_config_path,
    "bronze_config_path": bronze_config_path,
    "env": env
}

# COMMAND ----------

# Update job name
w.jobs.update(
    job_id=JOB_ID,
    new_settings=jobs.JobSettings(name=new_name)
)
print(f"Job {JOB_ID} updated successfully with new name: {new_name}")

# COMMAND ----------

# Trigger the job
try:
    run_by_id = w.jobs.run_now(job_id=JOB_ID, notebook_params=dynamic_params)
    print("Job triggered successfully.")
except Exception as e:
    print(f"Failed to trigger job: {str(e)}")