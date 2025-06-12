# Databricks notebook source
# MAGIC %pip install --upgrade databricks-sdk
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import time, os, json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import pipelines

# COMMAND ----------

dbutils.widgets.text('datasource_name', '', label='datasource Name')
dbutils.widgets.text('bronze_config_path', '', label='bronze_config_path')
dbutils.widgets.text('env', '', label='Enviornment variable')
datasource_name = dbutils.widgets.get("datasource_name")
bronze_config_path = dbutils.widgets.get("bronze_config_path")
env = dbutils.widgets.get("env") 

# COMMAND ----------

# Initialize Databricks SDK client
w = WorkspaceClient()

pipeline_name = f"{datasource_name} - Bronze"
print(pipeline_name)

# COMMAND ----------

def get_all_pipelines():
    try:
        all_pipelines = list(w.pipelines.list_pipelines())
        return all_pipelines
    except Exception as e:
        print(f"Failed to fetch pipelines: {str(e)}")
        return []

# COMMAND ----------

def get_catalog_and_schema(json_directory: str, env: str):
    """
    Reads the first uploaded JSON file in the specified directory and extracts 
    the catalog and schema name from target_definition.

    Args:
        json_directory (str): The directory where JSON files are stored.
        env (str): The environment (e.g., "dev", "qa", "prod") for selecting the catalog name.

    Returns:
        tuple: (catalog_name, schema_name) or (None, None) if no files exist.
    """
    # List all JSON files in the folder
    json_files = [f for f in os.listdir(json_directory) if f.endswith(".json")]

    # Check if JSON files are present
    if not json_files:
        print("No JSON files found in the specified folder.")
        return None, None

    # Get the full path and sort by creation time
    json_files_sorted = sorted(
        json_files, key=lambda f: os.stat(os.path.join(json_directory, f)).st_ctime
    )

    # Pick the first uploaded JSON file
    first_uploaded_file = json_files_sorted[0]
    file_path = os.path.join(json_directory, first_uploaded_file)
    
    print(f"Selected First Uploaded JSON File: {first_uploaded_file}")

    try:
        # Open and load JSON data
        with open(file_path, "r") as file:
            data = json.load(file)

        # Extract catalog and schema name from target_definition
        properties = data["source_to_target_definition"]["target_definition"]["data_store"]["properties"]

        # Check if catalog_name is a dictionary or a string
        catalog_name = properties["catalog_name"]
        if isinstance(catalog_name, dict):
            catalog_name = catalog_name.get(env, "UNKNOWN")  # Get catalog name for the specified env

        schema_name = properties["schema_name"]

        return catalog_name, schema_name

    except Exception as e:
        print(f"Error processing JSON file: {e}")
        return None, None


# COMMAND ----------

def create_pipeline(pipeline_name, bronze_config_path, catalog, schema, env):
    
    created_pipeline = w.pipelines.create(
        name=pipeline_name,
        development=True,
        continuous=False,
        channel="PREVIEW",
        photon=True,
        serverless=True,
        libraries=[
            pipelines.PipelineLibrary(notebook=pipelines.NotebookLibrary(
                path="/Workspace/Repos/main-repos/dnap-ingestion-framework/src/bronze/bronze_dlt"
            ))
        ],
        configuration={
            "configuration_path": bronze_config_path,
            "env": env,
            "utils_path": "/Workspace/Repos/main-repos/dnap-ingestion-framework"
    },
        catalog=catalog,
        edition="ADVANCED",
        schema=schema,
    )
    
    print(f"Pipeline created successfully: {created_pipeline.pipeline_id}")
    return created_pipeline.pipeline_id

# COMMAND ----------

def trigger_pipeline(pipeline_id):
    try:
        response = w.pipelines.start_update(pipeline_id=pipeline_id)
        print(f"Pipeline {pipeline_id} started successfully. Response: {response}")
    except Exception as e:
        print(f"Failed to start pipeline: {e}")

# COMMAND ----------

def main(pipeline_name, bronze_config_path):
    pipelines = get_all_pipelines()
    existing_pipeline = next((p for p in pipelines if p.name == pipeline_name), None)
    print(existing_pipeline)
    
    if existing_pipeline:
        pipeline_id = existing_pipeline.pipeline_id
        print(f"Existing pipeline found: {pipeline_id}. Triggering...")
    else:
        print("Pipeline not found. Creating a new one...")
        catalog, schema = get_catalog_and_schema(bronze_config_path, env)
        pipeline_id = create_pipeline(pipeline_name, bronze_config_path,catalog, schema, env)
    
    if pipeline_id:
        print("triggering the pipeline")
        trigger_pipeline(pipeline_id)

# COMMAND ----------

# main function calling
main(pipeline_name, bronze_config_path)