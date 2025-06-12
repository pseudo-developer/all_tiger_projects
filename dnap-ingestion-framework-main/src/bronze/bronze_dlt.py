# Databricks notebook source
# MAGIC %md
# MAGIC Setting Up Environment and Importing Dependencies for Delta Live Tables (DLT) Pipeline

# COMMAND ----------

import dlt
import json
import os
import sys
import pyspark.sql.types as T
from pyspark.sql.functions import *
from os import listdir
from os.path import isfile, join
sys.path.append(os.path.abspath(spark.conf.get('utils_path')+'/utils'))
import configuration, helper

# COMMAND ----------

# MAGIC %md
# MAGIC Fetching Bronze Configuration file Path 

# COMMAND ----------

configuration_path = spark.conf.get('configuration_path')

# COMMAND ----------

# MAGIC %md
# MAGIC Source Data Streaming: Reads and processes data from the source table, applying custom transformations if provided.
# MAGIC
# MAGIC Delta Live Table Creation: Creates a streaming Delta Live Table with a specified name and quality tag.
# MAGIC
# MAGIC Change Data Capture (CDC): Applies changes, including inserts, updates, and deletes, to the target table using primary keys and sequence columns.
# MAGIC
# MAGIC SCD Load Strategy: Handles Slowly Changing Dimension (SCD) logic if the load strategy specifies it, managing historical data updates.

# COMMAND ----------

def ingest_sql_table(
    source_catalog,
    source_schema,
    source_table_name,
    target_catalog,
    target_schema,
    target_table_name,
    primary_keys,
    seq_cols,
    except_column_list,
    load_strategy,
    partition_cluster_flag,
    partition_col
):

    # Initialize the cluster_by_property dictionary
    cluster_by_property = {}
    # Initialize the base table properties with "quality": "bronze"
    table_properties = {"quality": "bronze"}

    # Check the condition for `partition_cluster_flag` and `partition_col`
    if partition_cluster_flag == 'liquid' and len(partition_col) <= 4:
        # Get the column check result as a comma-separated string
        result_as_string = helper.get_initial_columns_with_check(source_catalog, source_schema, source_table_name, partition_col,except_column_list, return_as_list=False)
        # Add the "delta.dataSkippingStatsColumns" property to table_properties
        table_properties["delta.dataSkippingStatsColumns"] = f"{result_as_string}"
    
        # Populate the cluster_by_property dictionary with the required keys and values
        cluster_by_property = {
            "cluster_by": partition_col,
            "table_properties": table_properties
            }
    else:
        # Only add the basic "quality" property if the condition does not match
        cluster_by_property = {
            "table_properties": table_properties
            }

    # Create the streaming table with conditional `cluster_by` and table properties
    if "cluster_by" in cluster_by_property:
        dlt.create_streaming_table(
            name=f"{target_catalog}.{target_schema}.{target_table_name}",
            table_properties=cluster_by_property["table_properties"],
            cluster_by=cluster_by_property["cluster_by"]
            )
    else:
        dlt.create_streaming_table(
            name=f"{target_catalog}.{target_schema}.{target_table_name}",
            table_properties=cluster_by_property["table_properties"]
            )

    # Check if the 'pac_operation' column exists
    has_pac_operation = helper.column_exists(
        source_catalog, source_schema, source_table_name, "pac_operation"
    )
    
    # Prepare arguments for dlt.apply_changes()
    apply_changes_kwargs = {
        "target": f"{target_catalog}.{target_schema}.{target_table_name}",
        "source": f"{source_catalog}.{source_schema}.{source_table_name}",
        "keys": primary_keys,
        "sequence_by": seq_cols,
        "except_column_list": except_column_list,
        "stored_as_scd_type": load_strategy,
    }


    # Add 'apply_as_deletes' if 'pac_operation' column exists
    if has_pac_operation:
        apply_changes_kwargs["apply_as_deletes"] = expr("pac_operation = 'DELETE'")

    # Apply changes to the target table
    dlt.apply_changes(**apply_changes_kwargs)


# COMMAND ----------

# MAGIC %md
# MAGIC Load Bronze Configuration Files :
# MAGIC Retrieves the list of bronze configuration ![files](path) using the get_config_files function from the specified path.

# COMMAND ----------

bronze_config_file_path_list = helper.get_config_files(configuration_path)

# COMMAND ----------

# MAGIC %md
# MAGIC Validates input configurations: Ensures the bronze_config_file_path_list is correctly set.
# MAGIC
# MAGIC Processes multiple configuration files: Loads and extracts necessary details from each configuration.
# MAGIC
# MAGIC Extracts source and target details: Retrieves catalog, schema, and table names for both source and target.
# MAGIC
# MAGIC Prepares necessary parameters: Gathers key ingestion-related configurations for processing.
# MAGIC
# MAGIC Calls the ingestion function: Executes the ingestion process with the prepared parameters.

# COMMAND ----------

if bronze_config_file_path_list is None or not bronze_config_file_path_list:
    raise ValueError(
        "bronze_config_file_path_list is None. Ensure it is correctly set."
    )
else:
    print("Bronze config file paths:", bronze_config_file_path_list)
    for bronze_config_file_path in bronze_config_file_path_list:
        if bronze_config_file_path is None:
            raise ValueError(
                "bronze_config_file_path is None. Ensure it is correctly set."
            )
 
        env = spark.conf.get('env')
        print(f"Fetching configuration for environment: {env}")

        bronze_object = helper.load_pipeline_configs(bronze_config_file_path, env=env)
        if bronze_object is None:
            raise ValueError("bronze_object is None. Ensure it is correctly set.")

        # prepare ingestion parameters
        full_source_entity_name = bronze_object.full_source_entity_name
        full_source_entity_name_list = full_source_entity_name.split(".")
        source_catalog = full_source_entity_name_list[0]
        source_schema = full_source_entity_name_list[1]
        source_table_name = full_source_entity_name_list[2]

        full_target_entity_name = bronze_object.full_target_entity_name
        full_target_entity_name_list = full_target_entity_name.split(".")
        target_catalog = full_target_entity_name_list[0]
        target_schema = full_target_entity_name_list[1]
        target_table_name = full_target_entity_name_list[2]

        primary_keys = bronze_object.source_entity.property.get("primary_keys", [])

        seq_cols_list = bronze_object.source_entity.property.get("seq_col", [])
        seq_cols = ", ".join(seq_cols_list)

        except_column_list = bronze_object.source_entity.property.get(
            "except_column_list", []
        )
        partition_cluster_flag = bronze_object.target_definition.property.get("partition_cluster_flag","")
        partition_col = bronze_object.target_definition.property.get("partition_col", [])

        load_strategy = bronze_object.table_transform.load_strategy.get("mode")

        if "SCD" in load_strategy:
            load_strategy = load_strategy.split("_")[1]
        else:
            load_strategy = bronze_object.table_transform.load_strategy.get("mode")
        
        # Call the function with the source and target tables
        try:
            # Construct the fully qualified table name
            qualified_table_name = f"{source_catalog}.{source_schema}.{source_table_name}"
            print(f"qualified_table_name: Table {qualified_table_name}")
            if not helper.delta_table_exists(spark, qualified_table_name):
                raise ValueError(f"Warning: Table {qualified_table_name} does not exist.")
            else:
                # Call the function with the source and target tables
                ingest_sql_table(
                    source_catalog,
                    source_schema,
                    source_table_name,
                    target_catalog,
                    target_schema,
                    target_table_name,
                    primary_keys,
                    seq_cols,
                    except_column_list,
                    load_strategy,
                    partition_cluster_flag,
                    partition_col
                )
        except Exception as e: 
            # Log the error and continue with the next table 
            print(f"Error: {str(e)}. Skipping table: {source_catalog}.{source_schema}.{source_table_name}")
