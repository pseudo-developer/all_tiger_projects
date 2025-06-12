# Databricks notebook source
# MAGIC %md
# MAGIC ### Import Libraries

# COMMAND ----------

from typing import List, Dict, Optional
import json
import os
from utils import autogen_configuration as conf
from dataclasses import asdict

# COMMAND ----------

from pyspark.sql import SparkSession

# Create or get the Spark session
spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Retrieving Widget Values
# MAGIC
# MAGIC - **source_catalog_param**: The source catalog name
# MAGIC - **source_schema_param**: The source schema name
# MAGIC - **target_catalog_param**: The target catalog name
# MAGIC - **target_schem_param**: The target schema name
# MAGIC - **metadata_file_path_param**: The path for storing or retrieving metadata files
# MAGIC - **table_name_param**: Providing the table name is optional. However, if only specific tables JSON files are needed, they can be specified as comma-separated values.

# COMMAND ----------

# Retrieve the widget values
dbutils.widgets.text('source_catalog', '')
dbutils.widgets.text('source_schema', '')
dbutils.widgets.text('target_catalog', '')
dbutils.widgets.text('target_schema', '')
dbutils.widgets.text('metadata_file_path', '')
dbutils.widgets.text('table_name', '')
dbutils.widgets.text('file_config', '')
dbutils.widgets.dropdown('source_data_store_type', 'catalog', ['catalog', 'file'])
source_catalog_param = dbutils.widgets.get("source_catalog")
source_schema_param = dbutils.widgets.get("source_schema")
target_catalog_param = dbutils.widgets.get("target_catalog")
target_schema_param = dbutils.widgets.get("target_schema")
metadata_file_path_param = dbutils.widgets.get("metadata_file_path")
table_name_param = dbutils.widgets.get("table_name")
file_config_param = dbutils.widgets.get("file_config")
source_data_store_type_param = dbutils.widgets.get("source_data_store_type")


# COMMAND ----------

if file_config_param:
    file_config = json.loads(file_config_param)
    for file_config_input in file_config:
        file_config_output=conf.process_input(file_config_input)
        print(file_config_output)
else:
    file_config_output=None

# COMMAND ----------

# MAGIC %md
# MAGIC ### Function: `update_or_create_pipeline_json`
# MAGIC
# MAGIC The `update_or_create_pipeline_json` function generates or updates JSON configuration files for tables in a data pipeline. This function is designed to handle both single and multiple table names, which can be specified as comma-separated values in the `table_name` parameter. 
# MAGIC
# MAGIC #### Key Functionalities:
# MAGIC - **Fetching Table Details**: 
# MAGIC   - If `table_name` is provided, it splits this string into a list of table names.
# MAGIC   - If `table_name` is not provided, it retrieves all available tables from the specified source catalog and schema.
# MAGIC   
# MAGIC - **Building Configurations**: 
# MAGIC   - Creates configurations for source and target entities for each table, including attributes like data store type, schema, schema transformation maps, and transformation rules.
# MAGIC
# MAGIC - **File Handling**: 
# MAGIC   - For each table, a JSON file is generated and saved at the specified `metadata_file_path`.
# MAGIC   - If a file already exists, it updates only the `schema` field in the source entity and the `schema_transform_map` in the target entity. 
# MAGIC   - If the file does not exist, it creates a new JSON configuration file from scratch.

# COMMAND ----------

import os
import json
from dataclasses import asdict

def process_entity(entity_type, entity_list, source_catalog=None, source_schema=None, metadata_file_path=None, target_catalog=None, target_schema=None):

    pipeline_json = []
    for entity in entity_list:
        if entity_type == "table":
            try:
                table = entity
                entity_schema = spark.read.table(f"{source_catalog}.{source_schema}.{table}").schema
            except Exception as e:
                raise ValueError(f"Failed to read table {table}: {str(e)}")
        elif entity_type == "file":
            file_path = entity.get("file_path")
            file_format = entity.get("file_format", "csv")  # Default to CSV if format not specified
            trigger_type = entity.get("trigger_type")
            trigger_interval = entity.get("trigger_interval")
            source_spark_options = entity.get("source_spark_options")
            checkpointLocation = entity.get("checkpointLocation")

            
            # Read the schema from the file
            try:
                # Load the file(s)
                df, schema = conf.read_file_with_dynamic_support(
                    spark,
                    file_path,
                    file_format,
                    options=source_spark_options
                )
                entity_schema = schema
                table = os.path.basename(file_path).split('.')[0]  # Use file name as table name

            except Exception as e:
                raise ValueError(f"Failed to read file {file_path}: {str(e)}")
        
        # Updated structure to reflect the JSON layout
        # Create source and target entities using conf module (ensure it's properly imported)
        source_data_store_properties = {
            "catalog_name": {
                "dev": source_catalog,
                "qa": source_catalog,
                "stg": source_catalog,
                "prod": source_catalog
            },
            "schema_name": source_schema,
        }
        # Add properties conditionally based on entity_type presence
        if entity_type == "table":
            source_data_store_properties["table_name"] = table
        elif entity_type == "file":
            file_path = conf.format_file_path(file_path)
            source_data_store_properties["file_location"] = file_path
            source_data_store_properties["spark_options"] = {"cloudFiles.format": file_format}

        source_entity = conf.SourceEntity(
            data_store=conf.SourceDataStore(
                type=source_data_store_type_param,
                properties=conf.SourceDataStoreProperty(**source_data_store_properties)
            ),
            schema = conf.generate_source_json_from_schema(entity_schema),
            property=conf.SourceEntityProperty(
                primary_keys=[],
                watermark_column=None,
                initial_watermark_value= None,
                seq_col=[],
                except_column_list= []
            )
        )

        # Create a dictionary to hold the properties dynamically
        target_data_store_properties = {
            "catalog_name": {
                "dev": target_catalog,
                "qa": target_catalog,
                "stg": target_catalog,
                "prod": target_catalog
            },
            "schema_name": target_schema,
            "table_name":table
        }
        # Add properties conditionally based on entity_type presence
        if entity_type == "file":
            target_data_store_properties["trigger_type"] = trigger_type
            target_data_store_properties["trigger_interval"] = trigger_interval

            formatted_parts = ["/Volumes", "{catalog_name}", "{schema_name}", "checkpoints"] + [table]
            checkpointLocation_path = "/".join(formatted_parts) + "/"
            target_data_store_properties["spark_options"] = {"checkpointLocation": checkpointLocation_path}

    
        target_entity = conf.TargetEntity(
            data_store=conf.TargetDataStore(
                type="catalog",
                properties=conf.TargetDataStoreProperty(**target_data_store_properties)
            ),
            schema_transform_map = conf.generate_destination_json_from_schema(entity_schema),
            property=conf.TargetEntityProperty(
                primary_keys=[],
                seq_col=[],
                partition_cluster_flag="",
                partition_col=[]
            )
        )

        table_transform = conf.TableTransform(
            dedup=conf.DedupConfig(
                enabled=True,
                properties={"keys_override": []}
            ),
            cdc = conf.CdcConfig(
                enabled=False if entity_type == "file" else True,
                properties={} if entity_type == "file" else {"table_name_for_comparison": {
                    "dev": f"{source_catalog}.{source_schema}.bronze_{table}",
                    "qa": f"{source_catalog}.{source_schema}.bronze_{table}",
                    "stg": f"{source_catalog}.{source_schema}.bronze_{table}",
                    "prod": f"{source_catalog}.{source_schema}.bronze_{table}"
                    }
                                                             }
                ),
            load_strategy = conf.LoadStrategyConfig(
                stage_enabled = True,
                mode="append" if entity_type == "file" else "cdc append"
            )
        )

        rules = conf.Rules(
            bronze=conf.RulesConfig(
                Error=conf.RuleType(
                    literal=conf.Rule(rule=""),
                    derived=conf.Rule(rule="")
                ),
                Warn=conf.RuleType(
                    literal=conf.Rule(rule="")
                )
            )
        )

        pipeline_config = conf.SourceToTargetDefinition(
            source_entity=source_entity,
            target_definition=target_entity,
            table_transform=table_transform,
            rules=rules
        )

        # Convert the pipeline configuration to a dictionary with the top-level key
        pipeline_data = {"source_to_target_definition": asdict(pipeline_config)}

        # Define the file path for saving the JSON data
        file_path = f"{metadata_file_path}{table}.json"

        # Check if the file exists, and update schema and schema_transform_map if it does
        if os.path.exists(file_path):
            with open(file_path, "r") as file:
                existing_data = json.load(file)
            
            # Update only the schema in SourceEntity and schema_transform_map in TargetEntity
            existing_data["source_to_target_definition"]["source_entity"]["schema"] = pipeline_data["source_to_target_definition"]["source_entity"]["schema"]
            existing_data["source_to_target_definition"]["target_definition"]["schema_transform_map"] = pipeline_data["source_to_target_definition"]["target_definition"]["schema_transform_map"]
            
            # Use the modified existing data for the JSON output
            pipeline_data = existing_data

        # Write the pipeline configuration to the JSON file
        with open(file_path, "w") as file:
            json.dump(pipeline_data, file, indent=2)

        pipeline_json.append(json.dumps(pipeline_data, indent=2))

    return pipeline_json


# COMMAND ----------

def update_or_create_pipeline_json(
    spark: SparkSession,  # Pass the Spark session
    source_catalog: str, 
    source_schema: str, 
    target_catalog: str, 
    target_schema: str, 
    metadata_file_path: str, 
    table_name: Optional[str] = None,  # Optional table_name parameter
    file_config: Optional[list[str]] = None,
) -> List[Dict]:
    
    # Ensure the metadata_file_path ends with the appropriate separator
    if not metadata_file_path.endswith(os.sep):  # `os.sep` ensures cross-platform compatibility
        metadata_file_path += os.sep
    
    # Ensure that the metadata_file_path exists, create it if not
    if not os.path.exists(metadata_file_path):
        os.makedirs(metadata_file_path)

    if file_config:
        file_config = file_config
    # Fetch table names based on the optional table_name parameter
    elif table_name:
        table_names = [table.strip() for table in table_name.split(',')]
    else:
        table_names = conf.fetch_table_names(spark, source_catalog, source_schema)  # Get all table names if none specified

    # Process files if file_config is provided
    if file_config:
        return process_entity(
            entity_type="file", 
            entity_list=file_config,  # Pass file_config as entity_list
            source_catalog=source_catalog, 
            source_schema=source_schema,
            metadata_file_path=metadata_file_path,
            target_catalog=target_catalog, 
            target_schema=target_schema
        )
    # Process tables if table_name is provided
    elif table_name:
        return process_entity(
            entity_type="table", 
            entity_list=table_names,  # Pass table_names as entity_list
            source_catalog=source_catalog, 
            source_schema=source_schema,
            metadata_file_path=metadata_file_path,
            target_catalog=target_catalog, 
            target_schema=target_schema
        )
    else:
        return process_entity(
            entity_type="table", 
            entity_list=table_names,  # Pass table_names as entity_list
            source_catalog=source_catalog, 
            source_schema=source_schema,
            metadata_file_path=metadata_file_path,
            target_catalog=target_catalog, 
            target_schema=target_schema
        )

    

# COMMAND ----------

# MAGIC %md
# MAGIC ### Function Call: `update_or_create_pipeline_json`
# MAGIC
# MAGIC This function is responsible for either updating an existing JSON file or creating a new one based on the provided parameters. 
# MAGIC
# MAGIC #### Function Parameters:
# MAGIC - **`source_catalog` (str)**: The source catalog name for fetching data.
# MAGIC - **`source_schema` (str)**: The source schema name for fetching data.
# MAGIC - **`target_catalog` (str)**: The target catalog name for storing data.
# MAGIC - **`target_schema` (str)**: The target schema name for storing data.
# MAGIC - **`metadata_file_path` (str)**: Path to store the generated JSON configuration files.
# MAGIC - **`table_name` (Optional[str])**: Comma-separated table names to specify only particular tables for configuration (optional). If not provided, all tables in the source schema are used.

# COMMAND ----------

# calling the function
pipeline_json_data = update_or_create_pipeline_json(
    spark=spark,  # Pass the Spark session
    source_catalog=source_catalog_param,
    source_schema=source_schema_param,
    target_catalog=target_catalog_param,
    target_schema=target_schema_param,
    metadata_file_path=metadata_file_path_param,
    table_name=table_name_param,
    file_config=file_config_output # after processing using process_input()

)

# Print each JSON structure for each table
for pipeline in pipeline_json_data:
    print(pipeline)

# COMMAND ----------


