# Databricks notebook source
# MAGIC %pip install --upgrade databricks-sdk
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import time, os, json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import pipelines
from databricks.sdk.service.pipelines import PipelineSpec

# COMMAND ----------

dbutils.widgets.text('datasource_name', '', label='datasource Name')
dbutils.widgets.text('bronze_config_path', '', label='bronze_config_path')
dbutils.widgets.text('env', '', label='Environment variable')
dbutils.widgets.text('bronze_dlt_notebook_path', '', label='bronze_dlt_notebook_path')
dbutils.widgets.text('utils_path', '', label='utils_path')
dbutils.widgets.text('existing_pipeline', '', label='The exact case-sensitive name or UUID of the existing pipeline')
dbutils.widgets.dropdown("dry_run", "false", ["true", "false"], "dry-run")
datasource_name = dbutils.widgets.get("datasource_name")
bronze_config_path = dbutils.widgets.get("bronze_config_path")
env = dbutils.widgets.get("env") 
bronze_dlt_notebook_path = dbutils.widgets.get("bronze_dlt_notebook_path")
utils_path = dbutils.widgets.get("utils_path")
existing_pipeline_identifier = dbutils.widgets.get("existing_pipeline")
dry_run = dbutils.widgets.get("dry_run") == "true" # map to a boolean

# sets the default name if the identifier (id or name) isn't specified
default_pipeline_name = f"{datasource_name} - Bronze"

# COMMAND ----------

# Initialize Databricks SDK client
w = WorkspaceClient()

# COMMAND ----------

import re

def is_pipeline_uuid(s):
    pattern = re.compile(r'{?\w{8}-?\w{4}-?\w{4}-?\w{4}-?\w{12}}?')
    return bool(pattern.match(s))

# COMMAND ----------

def get_all_pipelines():
    try:
        all_pipelines = list(w.pipelines.list_pipelines())
        return all_pipelines
    except Exception as e:
        print(f"Failed to fetch pipelines: {str(e)}")
        return []

# COMMAND ----------

def get_pipeline(pipeline_id):
    try:
        pipeline = w.pipelines.get(pipeline_id)
        return pipeline.spec
    except Exception as e:
        print(f"Failed to fetch pipeline: {str(e)}")
        return None

# COMMAND ----------

def try_get_pipeline(pipleline_identifier: str) -> PipelineSpec:
    """
    Attempts to resolve the identifier (UUID or Name) and return an existing pipeline, otherwise returns nothing
    """
    try:
        pipeline = w.pipelines.get(pipleline_identifier)

        if pipeline:
            pipeline_spec = get_pipeline(pipeline.pipeline_id)
            return pipeline_spec
        
    except Exception as e:
        return None
    finally:
        try:
            pipelines = get_all_pipelines()
            pipeline = next((p for p in pipelines if p.name == pipleline_identifier), None)
            
            pipeline_spec = get_pipeline(pipeline.pipeline_id)
            return pipeline_spec
        except Exception as e:
            return None

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
# TODO: Add {env}-developer with CAN_MANAGE permissions
def create_pipeline(pipeline_name, bronze_config_path, catalog, schema, env):
    
    created_pipeline = w.pipelines.create(
        name=pipeline_name,
        development=False,
        continuous=False,
        channel="PREVIEW",
        photon=True,
        serverless=True,
        libraries=[
            pipelines.PipelineLibrary(notebook=pipelines.NotebookLibrary(
                path=bronze_dlt_notebook_path
            ))
        ],
        configuration={
            "configuration_path": bronze_config_path,
            "env": env,
            "utils_path": utils_path
    },
        catalog=catalog,
        edition="ADVANCED",
        schema=schema,
    )
    
    print(f"Pipeline created successfully: {created_pipeline.pipeline_id}")
    return created_pipeline.pipeline_id

# COMMAND ----------

def check_pipeline_config_changes(pipeline, configuration_path, utils_path):

    keys_to_check = {
        "configuration_path": configuration_path,
        "utils_path": utils_path
    }
    changes = {}
    
    for key, new_value in keys_to_check.items():
        current_value = pipeline.configuration[key]
        if current_value != new_value:
            changes[key] = {"current": current_value, "new": new_value}
    
    if not changes:
        print("No changes found in pipeline configurations.")
        return
    
    print("Changes found in pipeline configurations:")
    for key, change in changes.items():
        print(f"- {key}:")
        print(f"  - Current: {change['current']}")
        print(f"  - New: {change['new']}")
    return changes

# COMMAND ----------
# TODO: Fix update with "masking"
def update_pipeline(pipeline_spec: PipelineSpec, changes):
    if not changes:
        print("update_pipeline called but no changes were provided. Skipping...")
        return

    try:
        config = pipeline_spec.configuration

        if 'configuration_path' in changes:
            config['configuration_path'] = changes['configuration_path']['new']
        
        if 'utils_path' in changes:
            config['utils_path'] = changes['utils_path']['new']

        response = w.pipelines.update(
            pipeline_id=pipeline_spec.id,
            configuration=config
        )
        print(f"Pipeline {pipeline_spec.name}[{pipeline_spec.id}] updated successfully. Response: {response}")
    except Exception as e:
        print(f"Failed to update pipeline: {e}")
        raise

# COMMAND ----------

def trigger_pipeline(pipeline_id):
    try:
        response = w.pipelines.start_update(pipeline_id=pipeline_id)
        print(f"Pipeline {pipeline_id} started successfully. Response: {response}")
    except Exception as e:
        print(f"Failed to start pipeline: {e}")
        raise

# COMMAND ----------

def main(bronze_config_path):
    
    pipeline_identifier = existing_pipeline_identifier if existing_pipeline_identifier else f"{datasource_name} - Bronze"
    print(f"Input or default DLT pipeline name: {pipeline_identifier}")

    existing_pipeline_spec = try_get_pipeline(pipeline_identifier)
    if existing_pipeline_spec:
        # Check if the pipeline configuration has changed
        changes = check_pipeline_config_changes(existing_pipeline_spec, bronze_config_path, utils_path)

        if changes:
            print("WARNING: Pipeline configuration has changed, but the update is disabled in code. Please update the configuration manually!")
            #print("Pipeline configuration has changed. Updating...")
            
            #update_pipeline(existing_pipeline_spec, changes)

        print(f"Existing pipeline found: {existing_pipeline_spec.id}. Triggering...")
        pipeline_id = existing_pipeline_spec.id
    else:
        print("Pipeline not found. Creating a new one...")
        catalog, schema = get_catalog_and_schema(bronze_config_path, env)
        # don't create a pipeline with a UUID as the name if it didn't exist, fall back to the default
        # but do create a pipeline if a name is given but didn't exist
        pipeline_name = pipeline_identifier if not is_pipeline_uuid(pipeline_identifier) else default_pipeline_name
        pipeline_id = create_pipeline(pipeline_name, bronze_config_path,catalog, schema, env)
    
    if pipeline_id:
        print("triggering the pipeline")
        trigger_pipeline(pipeline_id)

# COMMAND ----------

# main function calling
main(bronze_config_path)
