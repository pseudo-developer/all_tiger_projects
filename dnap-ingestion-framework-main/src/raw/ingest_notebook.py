# Databricks notebook source
# MAGIC %md
# MAGIC #####Import required functions

# COMMAND ----------

import os
import sys
import pyspark.sql.functions as F
from databricks.sdk.runtime import *

# COMMAND ----------

# MAGIC %md
# MAGIC ##### Setup variables

# COMMAND ----------

dbutils.widgets.text('job_run_id', '-1', label='Job Run ID')
dbutils.widgets.text('task_run_id', '-1', label='Task Run ID')
dbutils.widgets.text('utils_path', '', label='Path to the Ingestion Framework Utils module')
dbutils.widgets.text('config_file', '', label='Full file path to the Table Configuration file')
dbutils.widgets.text('schema_prefix', '', label='Schema Prefix')
dbutils.widgets.text('env', '', label='Schema env')

# COMMAND ----------

# MAGIC %md
# MAGIC ##### Get input parameters

# COMMAND ----------

job_run_id     = dbutils.widgets.get('job_run_id')
task_run_id    = dbutils.widgets.get('task_run_id')
batch_id       = f'{job_run_id}-{task_run_id}'
config_file = dbutils.widgets.get('config_file')
schema_prefix = dbutils.widgets.get('schema_prefix')
env = dbutils.widgets.get('env')

sys.path.append(os.path.abspath(dbutils.widgets.get('utils_path')+"/utils"))
from utils.helper import *
from utils.transformation import *

# COMMAND ----------

# MAGIC %md 
# MAGIC loads pipeline configurations.
# MAGIC

# COMMAND ----------

try: 
    print(f"Fetching configuration for environment: {env}")
    
    # Load the pipeline configurations from the specified configuration file
    raw_object = load_pipeline_configs(config_file, env=env)

except Exception as e:
    # Handle any errors that occur during the process
    # Specific exception with the original error message included
    raise ValueError(f"Invalid Configuration: {str(e)}")

# COMMAND ----------

# MAGIC %md
# MAGIC Validate Config

# COMMAND ----------

# validate config
if not hasattr(raw_object, "validate") or not raw_object.validate():
    raise ValueError("Invalid Configuration")

# COMMAND ----------

# MAGIC %md
# MAGIC Extract various configuration values from raw_object

# COMMAND ----------

try:    
    load_strategy = raw_object.table_transform.load_strategy.get("mode")
    source_datasource_type = raw_object.source_entity.data_store.type
    target_datastore_type = raw_object.target_definition.data_store.type
    primary_keys = raw_object.source_entity.property.get("primary_keys", [])
    watermark_column = raw_object.source_entity.property.get("watermark_column", None)
    initial_watermark_value = raw_object.source_entity.property.get(
        "initial_watermark_value", None
    )
    cdc_config = raw_object.table_transform.cdc
    source_schema = raw_object.source_entity.schema
    schema_transform_map = raw_object.target_definition.schema_transform_map
    partition_col_list = raw_object.target_definition.property.get('partition_col', [])
    partition_cluster_flag = raw_object.target_definition.property.get('partition_cluster_flag', "")
    file_location = raw_object.source_entity.data_store.properties.get("file_location", "")
    table_name = raw_object.source_entity.data_store.properties.get("table_name", "")
    spark_options = raw_object.source_entity.data_store.properties.get("spark_options", "")
    target_spark_options = raw_object.target_definition.data_store.properties.get("spark_options", "")
    trigger_type = raw_object.target_definition.data_store.properties.get("trigger_type", "")
    trigger_interval = raw_object.target_definition.data_store.properties.get("trigger_interval", "")
    full_source_entity_name = ''
    dedup_config = raw_object.table_transform.dedup
    stage_enabled = raw_object.table_transform.load_strategy.get("stage_enabled", True)

except Exception as e:
    # specific exception with the original error message included
    raise ValueError(f"Invalid Configuration: {str(e)}")

# COMMAND ----------

try:    
    # Check if the source datasource type is supported
    if source_datasource_type == "catalog":
        if table_name not in ("", None):
            print("table_name", table_name)
            # Get the source entity name
            full_source_entity_name = raw_object.full_source_entity_name
            print("full_source_entity_name", full_source_entity_name)
        elif file_location  not in ("", None):
            file_location = set_dynamic_file_location(raw_object.source_entity.data_store.properties, file_location, env)
            print("file_location", file_location)
        else:
            raise ValueError("Neither table_name nor file_location is provided for catalog source")
    
    elif source_datasource_type == "file":
        if file_location:
            file_location = raw_object.property.file_location
    else:
        raise ValueError("source_datasource_type is not recognized")

    # Check if the target datastore type is 'catalog'
    if target_datastore_type != "catalog":
        raise ValueError("target_datasource_type is not found")       

    # Get the target entity name
    catalog, schema, table = raw_object.full_target_entity_name.split('.')
    full_target_stage_entity_name = catalog + '.' + schema_prefix + schema + '.' + table + '_stage'
    print("full_target_stage_entity_name", full_target_stage_entity_name)
    full_target_entity_name = catalog + '.' + schema_prefix + schema + '.' + table
    print("full_target_entity_name", full_target_entity_name)
    
    bronze_full_target_entity_name=''
    # Check if CDC (Change Data Capture) is enabled
    if cdc_config.enabled :
        if file_location in ("", None):
            # Get the table name for comparison from CDC config properties
            table_name_for_comparison = cdc_config.properties.get("table_name_for_comparison", "")
            if isinstance(table_name_for_comparison, dict):
                # Extract the value for the current environment if it's a dictionary
                bronze_full_target_entity_name = table_name_for_comparison.get(env, "")
            elif isinstance(table_name_for_comparison, str):
                # Use the string value directly if it's not a dictionary
                bronze_full_target_entity_name = table_name_for_comparison
            print(f"Table Name for Comparison: {bronze_full_target_entity_name}")
        else:
            raise ValueError("File handling not supported for CDC enabled configurations")
    else:
        print("CDC is disabled")

except Exception as e:
# Catch and handle any errors that occur
    print(f"Failed {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC - Watermark Handling: This block ensures that only new or changed data is processed by using the maximum watermark value from the source data.
# MAGIC - Flexible Querying: The code adapts to whether a watermark column is provided or not, and it constructs the appropriate queries accordingly.

# COMMAND ----------

try:
    if source_datasource_type == "catalog" and table_name  not in ("", None): 
        watermark_value = get_watermark_value(bronze_full_target_entity_name, watermark_column, initial_watermark_value)

        # Build the source query
        query = build_source_query(full_source_entity_name, watermark_column, watermark_value, source_schema, schema_transform_map)

        if stage_enabled:
            # Drop the stage table if exists
            spark.sql(f"DROP TABLE IF EXISTS {full_target_stage_entity_name}")
            # Create the stage table
            spark.sql(f"CREATE TABLE {full_target_stage_entity_name} AS {query}")

            # Fetch the data from the stg_tablename
            raw_Df = spark.table(full_target_stage_entity_name)
        else:
            # Fetch the data from the source
            raw_Df = get_df_from_source(source_datasource_type, query=query)
    
    elif source_datasource_type in ("catalog" ,"file") and file_location!='':
        # Create schema
        schema = create_schema_from_transform_map(source_schema)
        # Load the data from the source
        raw_Df = file_loader(file_location,spark_options,schema)

except Exception as e:
    # Handle any exceptions that occur during the process
    print(f"Failed {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC Apply the custom transformation on raw_DF

# COMMAND ----------

raw_Df_transformed = add_dynamic_columns_with_type_check(raw_Df, schema_transform_map, apply_only_derived=False)

# COMMAND ----------

# MAGIC %md
# MAGIC - Delta Table Existence Check: The code checks if the source and target delta tables exist. If they do, it proceeds with transformations or data loading. If not, it handles the case as an insert operation (for the target table).
# MAGIC - Transformation: If the source table exists, the code adds a hash key to the source DataFrame using a custom transformation function (helper.add_hash_key).
# MAGIC - Target Table Filtering: If the target table (bronze) exists, the code filters out records where the __END_AT column is not null in case of SCD Typ-2 at Bronze layer else it will read entire table.
# MAGIC - Fallback for Missing Target Table: If the target table doesn’t exist, it creates an empty DataFrame and treats incoming data as new inserts.

# COMMAND ----------

try:
    # Add a hash key column to the raw dataframe based on primary keys or non-primary keys
    source_Df = raw_Df_transformed.transform(add_hash_key, primary_keys)

    if cdc_config.enabled and file_location in ("", None):

        # Check if the bronze (target) delta table exists
        if delta_table_exists(spark, bronze_full_target_entity_name):
            print(f"Bronze table {bronze_full_target_entity_name} exists.")
            # Load the existing bronze table into a DataFrame
            target_Df = spark.table(bronze_full_target_entity_name)
            # If the "__END_AT" column exists, filter out rows that are marked as ended
            if "__END_AT" in target_Df.columns:
                target_Df = target_Df.filter(F.col("__END_AT").isNull())

        else:
            # If the bronze table does not exist, create an empty DataFrame with a 'pac_hash_key' column
            print(f"bronze table {bronze_full_target_entity_name} doesn't exists, consider all records as insert.")
            target_Df = spark.createDataFrame([], "pac_hash_key string")
    elif not cdc_config.enabled and file_location in ("", None):
        print("cdc is disabled and file is disabled, setting target as source")
        target_Df = source_Df

except Exception as e:
    # Handle any errors that occur during the execution
    print(f"Failed {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC - CDC Operation: The code performs a Change Data Capture (CDC) operation to capture only the changed records from the source DataFrame compared to the target DataFrame.
# MAGIC - Exclusion of Specific Columns: The pac_operation and pac_load_timestamp columns are excluded from the CDC comparison, ensuring that the CDC logic only compares relevant data.
# MAGIC - Load Strategy and Timestamp: If new changes are found and the strategy is 'cdc append', the code appends the changes to the target delta table and adds a load_timestamp for tracking when the records are ingested.

# COMMAND ----------

try:
    # Define columns to exclude from the CDC operation (e.g., pac_operation, pac_load_timestamp)
    exclude_cols = ["pac_operation", "pac_load_timestamp", "pac_batch_id"]
    load_type = None

    # Check if CDC is disabled and if the source DataFrame is streaming
    if not cdc_config.enabled and source_Df.isStreaming:
        print("CDC is disabled, streaming ingestion is enabled.")
        
        # Add ETL columns to the source DataFrame
        cdc_Df_transformed = add_etl_cols(source_Df, batch_id)
        # Check if "checkpointLocation" is provided in target_spark_options
        if not target_spark_options.get("checkpointLocation"):
            # Throw an error if "checkpointLocation" is not found
            raise KeyError("checkpointLocation key is missing in target_spark_options")
        checkpointlocation = set_dynamic_file_location(raw_object.source_entity.data_store.properties, target_spark_options.get("checkpointLocation"), env)
        print("checkpointlocation", checkpointlocation)

        # Create the volume if it does not exist
        # Split the file path by '/'
        checkpointlocation_parts = checkpointlocation.split('/')
        
        # Extract the catalog name from the split parts (3rd item)
        checkpoint_catalog = checkpointlocation_parts[2]
        # Extract the schema name from the split parts (4th item)
        checkpoint_schema = checkpointlocation_parts[3]
        # Extract the volume name from the split parts (5th item)
        checkpoint_volume = checkpointlocation_parts[4]

        # Check if the volume exists using a helper function
        if not volume_exists(checkpoint_catalog, checkpoint_schema, checkpoint_volume):
            # If the volume does not exist, create a query to create the volume
            create_query = f"CREATE VOLUME {checkpoint_catalog}.{checkpoint_schema}.{checkpoint_volume}"
            # Execute the query using Spark SQL to create the volume
            spark.sql(create_query)
            # Print a message indicating the volume was created successfully
            print(f"Volume {checkpoint_volume} created successfully.")
        else:
            # If the volume already exists, print a message indicating this
            print(f"Volume {checkpoint_volume} already exists.")
        target_spark_options["checkpointLocation"] = checkpointlocation
        # Write the transformed DataFrame to Delta stream    
        write_delta_stream(cdc_Df_transformed, full_target_entity_name, load_strategy, trigger_type,trigger_interval, target_spark_options)

    elif not cdc_config.enabled and not source_Df.isStreaming:
        print("CDC is disabled, streaming ingestion is disabled.")
        print("Saving table with overwrite on.")

        target_Df.write.mode("overwrite").saveAsTable(full_target_entity_name)

    # Check if CDC is enabled and if the source DataFrame is not streaming
    elif cdc_config.enabled:
        print("CDC is enabled, streaming ingestion is disabled.")    
        # Build the CDC DataFrame by comparing the source and target data, considering the primary keys and watermark column

        # initial-data load
        # Check if the Delta table exists and assign the corresponding raw table DataFrame
        if delta_table_exists(spark, full_target_entity_name):
            print("delta table exists ",delta_table_exists(spark, full_target_entity_name))
            raw_table =  spark.table(full_target_entity_name)
        else:
            raw_table = spark.createDataFrame([], "pac_hash_key string")

        # Check if the raw table is empty and initial data load - record considered as insert
        if raw_table.isEmpty() or not delta_table_exists(spark, full_target_entity_name):
            cdc_Df = source_Df.withColumn('pac_operation', F.lit('INSERT'))
            print("No records in raw table -  initial data load")
            load_type = "initial"

        # Build the CDC DataFrame if the target DataFrame is not empty and not initial data load
        elif not target_Df.isEmpty():
            cdc_Df = build_cdc(
                source_Df, target_Df, exclude_cols, primary_keys, watermark_column
            )
        else:
            print("No new records to ingest Raw.")
        
        try:
            # Check if cdc_Df exists and has new data
            if 'cdc_Df' in locals() and cdc_Df is not None:

                print("cdc Df exists and has new data")
                if not cdc_Df.isEmpty():
                    
                    # Proceed with your logic here
                    print("CDC DataFrame built successfully.")
                    # Check if load strategy is 'cdc append'
                    if load_strategy == "cdc append":
                        
                        # Apply ETL transformations to the CDC DataFrame
                        cdc_Df_transformed = add_etl_cols(cdc_Df, batch_id)

                        # Check if deduplication is enabled
                        if dedup_config.enabled:
                            print("dedup enabled")
                            dedup_key = dedup_config.properties.get('keys_override', [])
                            cdc_Df_transformed = dedup(cdc_Df_transformed, key=dedup_key)

                        # Call the function and write the data to the Delta table with the specified partitioning and clustering logic.
                        write_data_to_delta(cdc_Df_transformed, full_target_entity_name, partition_col_list, partition_cluster_flag)

                    else:
                        print("Load strategy is not 'cdc append'.")
                else:
                    # Check if the source DataFrame is empty and the Raw table does not exist  
                    if not delta_table_exists(spark, full_target_entity_name):
                        print("Source table is empty and Raw table does not exist.")
                        
                        # Create an empty DataFrame with required columns to maintain schema 
                        cdc_Df=cdc_Df.withColumn("pac_batch_id", F.lit("")) \
                        .withColumn("pac_load_timestamp", F.lit(None).cast("timestamp"))

                        # Write the empty DataFrame to the target table to ensure the table is created
                        # Call the function and write the data to the Delta table with the specified partitioning and clustering logic
                        write_data_to_delta(cdc_Df, full_target_entity_name, partition_col_list, partition_cluster_flag)
                    else:
                        print("cdc_Df is empty and No new records to ingest.")

            else:
                print("cdc_Df is not defined or contains no new data. No action is required.")
                
        except NameError as e:
            # Handle NameError specifically for cdc_Df
            if 'cdc_Df' in str(e):
                print(f"NameError occurred for cdc_Df: {e}. No new data in the source.")
            else:
                raise  # Re-raise the exception if it's not related to cdc_Df

        except Exception as e:
            # Generic exception handling
            print(f"An unexpected error occurred: {e}")
            raise

    if stage_enabled:
        spark.sql(f"DROP TABLE IF EXISTS {full_target_stage_entity_name}")

except Exception as e:
    # Catch any exceptions that occur during the process
    print(f"Failed {str(e)}")
    raise
