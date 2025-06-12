# Databricks notebook source
# MAGIC %md
# MAGIC In this notebook we are mainly tring to interact with foreign catalog and our native catalog tables (respective to foreign catalog table) and check the count and exact data if they match or not. We are taking the path to config (jsons) files directory of a particular source lets say - ptsjet,CES1,CES2,etc, and then later we also have a option "tables" variable (list) which gives the flexibility to look for a limited set of tables's json from the given config file directory.
# MAGIC Once for a particular config file read from the specified location, we run the count-check and row-to-row data check (using subtract clause in pyspark) and extract all possible information from cionfig like landing_table_name, bronze_table_name, etc.  Also we figure out from json itself, that whether the given table is having watermark_column or not, if not we consider it null (a string value, not python None) [this was done by misake, but since its working so working]. Once we are aware if the table is a watermark column or not, we can process the QC check based on whether we have to check its full data or based on its incremental data after 2nd last run (latest run, 2nd last run, 3rd last run....)
# MAGIC
# MAGIC Once these information is available, is passed to the main runner code (in last cell) to execute the "bronze-subtract-landing" check along with count check between the two layers. NOTE - We have a parameter called "ifLandingToBronzeCheckActi" which if enabled, the notebook will executing the "bronze-subtract-landing" (mandatory) + the (optional) "landing-subtract-bronze" check

# COMMAND ----------

# DBTITLE 1,Sample json file structure (might be from a random source
{
  "source_to_target_definition": {
    "source_entity": {
      "data_store": {
        "type": "catalog",
        "properties": {
          "catalog_name": {
            "dev": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa",
            "qa": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa",
            "stg": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa",
            "prod": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa"
          },
          "schema_name": "dbo",
          "table_name": "tblOtherEquipmentJoin",
          "file_location": null,
          "spark_options": {}
        }
      },
      "schema": [
        {
          "column_name": "OtherEquipmentJoinID",
          "data_type": "int",
          "nullable": true
        },
        {
          "column_name": "OtherEquipmentID",
          "data_type": "int",
          "nullable": true
        },
        {
          "column_name": "ItemsID",
          "data_type": "int",
          "nullable": true
        }
      ],
      "property": {
        "primary_keys": ["OtherEquipmentJoinID"],
        "watermark_column": null,
        "initial_watermark_value": null,
        "seq_col": [],
        "except_column_list": []
      }
    },
    "target_definition": {
      "data_store": {
        "type": "catalog",
        "properties": {
          "catalog_name": {
            "dev": "ces_agency_demodb_cdsj_dev",
            "qa": "ces_agency_demodb_cdsj_dev",
            "stg": "ces_agency_demodb_cdsj_dev",
            "prod": "ces_agency_demodb_cdsj_dev"
          },
          "schema_name": "dbo_raw",
          "table_name": "tblOtherEquipmentJoin_cdc",
          "trigger_type": null,
          "trigger_interval": null,
          "spark_options": {}
        }
      },
      "schema_transform_map": [
        {
          "column_name": "OtherEquipmentJoinID",
          "source_column_name": "OtherEquipmentJoinID",
          "type": "int",
          "derived_expression": ""
        },
        {
          "column_name": "OtherEquipmentID",
          "source_column_name": "OtherEquipmentID",
          "type": "int",
          "derived_expression": ""
        },
        {
          "column_name": "ItemsID",
          "source_column_name": "ItemsID",
          "type": "int",
          "derived_expression": ""
        }
      ],
      "property": {
        "primary_keys": [],
        "seq_col": [],
        "partition_cluster_flag": "",
        "partition_col": []
      }
    },
    "table_transform": {
      "dedup": {
        "enabled": true,
        "properties": {
          "keys_override": []
        }
      },
      "cdc": {
        "enabled": true,
        "properties": {
          "table_name_for_comparison": {
            "dev": "ces_agency_demodb_cdsj_dev.dbo_bronze.tblOtherEquipmentJoin",
            "qa": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa.dbo.bronze_tblOtherEquipmentJoin",
            "stg": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa.dbo.bronze_tblOtherEquipmentJoin",
            "prod": "foreign_panama_ces_agency_demodb_cdsj_int02b_qa.dbo.bronze_tblOtherEquipmentJoin"
          }
        }
      },
      "load_strategy": {
        "stage_enabled": true,
        "mode": "cdc append"
      }
    },
    "rules": {
      "bronze": {
        "Error": {
          "literal": {
            "rule": ""
          },
          "derived": {
            "rule": ""
          }
        },
        "Warn": {
          "literal": {
            "rule": ""
          },
          "derived": null
        }
      }
    }
  }
}

# COMMAND ----------

# %sql
# WITH ordered_tables AS (
#   SELECT 
#     source_table_name,
#     source_table_count,
#     bronze_table_count,
#     mismatch_record_count_in_bronze,
#     created_at,
#     LEAD(created_at) OVER (ORDER BY created_at) AS ended_at
#   FROM dnap_prod.default.qc_results
# ),
# with_processing_time AS (
#   SELECT
#     source_table_name,
#     (UNIX_TIMESTAMP(ended_at) - UNIX_TIMESTAMP(created_at)) AS time_taken_seconds,
#     ROUND((UNIX_TIMESTAMP(ended_at) - UNIX_TIMESTAMP(created_at))/ 60, 2) AS time_taken_minutes,
#     source_table_count,
#     bronze_table_count,
#     mismatch_record_count_in_bronze,
#     created_at AS process_start_time,
#     ended_at AS process_end_time
#   FROM ordered_tables
# )
# SELECT *
# FROM with_processing_time
# ORDER BY time_taken_minutes desc

# -- 88.32 + 26.72 + 25.85 + 21.42 + 17.03 + 15.1 + 13.82 + 13.63 + 11.1 + 10.95 + 10.15 + 9.73 + 8.28 + 7.78 + 7.35 + 7.18 + 6.5 + 5.68 + 5 + 4.47 + 4.4 + 4.38 + 4.12 + 3.87 + 3.57 + 3.48 + 3.42 + 3.38 + 3.35 + 3.17 + 3.13 = 372.83

# COMMAND ----------

# %sql
# WITH ordered_tables AS (
#   SELECT 
#     source_table_name,
#     source_table_count,
#     bronze_table_count,
#     mismatch_record_count_in_bronze,
#     created_at,
#     LEAD(created_at) OVER (ORDER BY created_at) AS ended_at
#   FROM dnap_prod.default.qc_results
# ),
# with_processing_time AS (
#   SELECT
#     source_table_name,
#     source_table_count,
#     bronze_table_count,
#     mismatch_record_count_in_bronze,
#     created_at AS process_start_time,
#     ended_at AS process_end_time,
#     (UNIX_TIMESTAMP(ended_at) - UNIX_TIMESTAMP(created_at)) AS time_taken_seconds,
#     ROUND((UNIX_TIMESTAMP(ended_at) - UNIX_TIMESTAMP(created_at))/ 60, 2) AS time_taken_minutes
#   FROM ordered_tables
# ),
# with_size_buckets AS (
#   SELECT
#     *,
#     CASE
#       WHEN source_table_count < 1000 THEN '<1K'
#       WHEN source_table_count >= 1000 AND source_table_count < 10000 THEN '1K-10K'
#       WHEN source_table_count >= 10000 AND source_table_count < 100000 THEN '10K-100K'
#       WHEN source_table_count >= 100000 THEN '>100K'
#       ELSE 'Unknown'
#     END AS count_bucket
#   FROM with_processing_time
# )
# SELECT 
#   count_bucket,
#   COUNT(*) AS tables_processed,
#   ROUND(AVG(time_taken_seconds), 2) AS avg_time_seconds,
#   ROUND(AVG(time_taken_minutes), 2) AS avg_time_minutes,
#   ROUND(MIN(time_taken_seconds), 2) AS min_time_seconds,
#   ROUND(MAX(time_taken_seconds), 2) AS max_time_seconds
# FROM with_size_buckets
# GROUP BY count_bucket
# ORDER BY 
#   CASE count_bucket
#     WHEN '<1K' THEN 1
#     WHEN '1K-10K' THEN 2
#     WHEN '10K-100K' THEN 3
#     WHEN '>100K' THEN 4
#     ELSE 5
#   END;


# COMMAND ----------

# /Workspace/Users/anirudh.busarapalli@advantagesolutions.net/Data_validation/Jsons/raw - 329 jsons
# /Workspace/Users/anirudh.busarapalli@advantagesolutions.net/Data_validation/json - 2 sample jsons

# COMMAND ----------

# DBTITLE 1,Run from here
# All necessary imports
from pyspark.sql.functions import *
import json
from typing import List, Optional
import os # Import the os module to list files in a directory
import uuid # For generating run_id
from datetime import datetime # For created_at timestamp
import uuid
from pyspark.sql import SparkSession, DataFrame, Column
from pyspark.sql import functions as F
from pyspark.sql import types as T


# dbutils.widgets.removeAll()

# Changed to accept a directory path for configuration files
dbutils.widgets.text('config_files_directory', '', label='Full path to the directory containing Table Configuration files')
dbutils.widgets.text('ifCheckForFullLoad', '', label='Forced full load QC check for the table')
dbutils.widgets.text('qc_results_table_full_name', 'qc_results', label='Full path to the QC Results Delta Table (e.g., catalog.schema.table)')
dbutils.widgets.text('data_source', "")
dbutils.widgets.text('ifLandingToBronzeCheckActive', "")

config_files_directory = dbutils.widgets.get('config_files_directory')
ifCheckForFullLoad_str = dbutils.widgets.get('ifCheckForFullLoad')
qc_results_table_full_name = dbutils.widgets.get('qc_results_table_full_name')
data_source = dbutils.widgets.get('data_source')
ifLandingToBronzeCheckActive_str = dbutils.widgets.get('ifLandingToBronzeCheckActive')

# Convert the string to a boolean (case-insensitive)
ifCheckForFullLoad = ifCheckForFullLoad_str.lower() == 'true'
ifLandingToBronzeCheckActive = ifLandingToBronzeCheckActive_str.lower() == 'true'

print("config_files_directory : ", config_files_directory)
print("ifCheckForFullLoad : ", ifCheckForFullLoad)
print("qc_results_table_full_name : ", qc_results_table_full_name)
print("data_source : ", data_source)
print("ifLandingToBronzeCheckActive : ", ifLandingToBronzeCheckActive)

# COMMAND ----------

# DBTITLE 1,read and frame data functions
# params function
def get_query_params_from_config(path_to_json):
    """
    Accepts path to a single JSON file and returns the query parameters.
    Returns None for all parameters if an error occurs during parsing.
    """

    try:
        with open(path_to_json, 'r') as f:
            lan_to_raw_json_data = json.load(f)

        source_datasource_type = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['type']
        
        # LANDING layer properties
        #landing_catalog_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['catalog_name']
        landing_catalog_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['catalog_name']['prod']
        landing_schema_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['schema_name']
        landing_table_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['table_name']
        landing_table_full_entity_name = f"{landing_catalog_name}.{landing_schema_name}.{landing_table_name}"

        # RAW layer properties
        #raw_catalog_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['catalog_name']
        raw_catalog_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['catalog_name']['prod']
        raw_schema_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['schema_name']
        raw_table_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['table_name']
        raw_table_full_entity_name = f"{raw_catalog_name}.{raw_schema_name}.{raw_table_name}"

        # BRONZE layer properties
        #bronze_table_full_entity_name = lan_to_raw_json_data['source_to_target_definition']['table_transform']['cdc']['properties']['table_name_for_comparison']
        bronze_table_full_entity_name = lan_to_raw_json_data['source_to_target_definition']['table_transform']['cdc']['properties']['table_name_for_comparison']['prod']

        # ALIAS COLUMNS for schema transformation
        schema_transform_map_list = lan_to_raw_json_data['source_to_target_definition']['target_definition']['schema_transform_map']
        landing_columns_aliased = [F.col(item['source_column_name']).alias(item['column_name']) for item in schema_transform_map_list]

        # OTHER INFO
        watermark_column_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['watermark_column']
        primary_keys_list = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['primary_keys']
        except_column_list = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['except_column_list']

        # Final column lists for selection, excluding specified columns
        final_landing_column_list_to_select = [col for col in landing_columns_aliased if col.alias not in except_column_list]
        final_column_list_to_select = [F.col(item['column_name']) for item in schema_transform_map_list if item['column_name'] not in except_column_list]

        print(f"Params fetched from file {path_to_json} :-")
        print("source_datasource_type:", source_datasource_type)
        print("landing_table_full_entity_name:", landing_table_full_entity_name)
        print("raw_table_full_entity_name:", raw_table_full_entity_name)
        print("bronze_table_full_entity_name:", bronze_table_full_entity_name)
        print("watermark_column_name:", watermark_column_name)
        print("primary_keys_list:", primary_keys_list)
        print("final_landing_column_list_to_select :", final_landing_column_list_to_select)
        print("final_column_list_to_select:", final_column_list_to_select)
        
        return lan_to_raw_json_data, source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name, primary_keys_list, final_landing_column_list_to_select, final_column_list_to_select
        
    except Exception as e:
        print(f"An error occurred while parsing {path_to_json}: {e}")
        return None, None, None, None, None, None, None, None, None


def get_second_max_version_bronze(bronze_table_full_entity_name):
    """
    Retrieves the second maximum version from the history of a Delta table,
    used for determining the previous state in incremental loads.
    """
    history_df = spark.sql(f"DESC HISTORY {bronze_table_full_entity_name}").where("operation = 'MERGE'").orderBy("version", ascending=False)    
    if history_df.count() >= 2:
        is_first_time_load = False
        second_max_version_bronze = history_df.select('version').take(2)[1]['version']
        print("second_max_version_bronze is : ",second_max_version_bronze)
    else:
        is_first_time_load = True
        second_max_version_bronze = None  # No second version, likely a first time load or only one merge
    
    return second_max_version_bronze, is_first_time_load


def get_max_prev_watermark_value_bronze(bronze_table_full_entity_name, watermark_column_name, second_max_version_bronze) -> int:
    """
    Fetches the maximum watermark value from the previous version of the bronze table.
    """
    if spark.catalog.tableExists(bronze_table_full_entity_name):
        if watermark_column_name and second_max_version_bronze is not None:
            max_prev_watermark_value_bronze = spark.sql(f"""
                SELECT MAX({watermark_column_name}) AS max_watermark_value FROM (
                    select * from {bronze_table_full_entity_name} version as of {second_max_version_bronze}
                )
            """).collect()[0][0]
            print("max_prev_watermark_value_bronze is :",max_prev_watermark_value_bronze)
            return max_prev_watermark_value_bronze
        else:
            print(f"Watermark column '{watermark_column_name}' is not defined or no previous version exists for {bronze_table_full_entity_name}. Returning None.")
            return None
    else:
        print(f"Table {bronze_table_full_entity_name} does not exist. This is likely the first time load.")
        return None


# fetch data
def fetch_full_table_data(landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, final_landing_column_list_to_select, final_column_list_to_select):
    """
    Fetches full data from landing, raw, and bronze layers.
    """
    landing_data = spark.table(landing_table_full_entity_name).select([*final_landing_column_list_to_select])
    raw_data = spark.table(raw_table_full_entity_name).select([*final_column_list_to_select])
    # Filter bronze data for current active records (__END_AT is null)
    bronze_data = spark.table(bronze_table_full_entity_name).where(F.col('__END_AT').isNull())
    return landing_data, raw_data, bronze_data

def fetch_incremental_table_data(landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name : str, second_max_version_bronze, final_landing_column_list_to_select, final_column_list_to_select):
    """
    Fetches incremental data from landing, raw, and bronze layers based on watermark.
    """
    max_prev_watermark_value_bronze = get_max_prev_watermark_value_bronze(bronze_table_full_entity_name, watermark_column_name, second_max_version_bronze)

    if max_prev_watermark_value_bronze is None:
        print(f"No previous watermark value found for incremental load. Fetching full data for {bronze_table_full_entity_name}.")
        return fetch_full_table_data(landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, final_landing_column_list_to_select, final_column_list_to_select)

    landing_data = spark.table(landing_table_full_entity_name).select([*final_landing_column_list_to_select]).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    raw_data = spark.table(raw_table_full_entity_name).select([*final_column_list_to_select]).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    # Filter bronze data for current active records and incremental changes
    bronze_data = spark.table(bronze_table_full_entity_name).where(F.col('__END_AT').isNull()).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    
    return landing_data, raw_data, bronze_data

def fetch_data_for_qc(source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name : str, ifCheckForFullLoad : bool = True, final_landing_column_list_to_select = None, final_column_list_to_select = None):
    """
    Determines whether to fetch full or incremental data for QC based on configuration and table history.
    """
    if source_datasource_type == 'catalog':
        if watermark_column_name:
            print(f"Watermark column exists : `{watermark_column_name}`")

            if ifCheckForFullLoad:
                print(f"FORCED QC check for FULL LOAD of Incremental bronze table {bronze_table_full_entity_name} data. Fetching today's data from all layers...")
                landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
                return landing_data, raw_data, bronze_data

            else:
                second_max_version_bronze, is_first_time_load = get_second_max_version_bronze(bronze_table_full_entity_name)
                if is_first_time_load:
                    print(f"FIRST TIME LOAD of Incremental bronze table {bronze_table_full_entity_name} data. Fetching today's data from all layers...")
                    landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
                    return landing_data, raw_data, bronze_data
                else:
                    print("NOT first time load of this Incremental bronze table data. Fetching today's data from all layers...")
                    landing_data, raw_data, bronze_data = fetch_incremental_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,watermark_column_name,second_max_version_bronze, final_landing_column_list_to_select,final_column_list_to_select)
                    return landing_data, raw_data, bronze_data

        else:
            print("Watermark column DOES NOT exist or is not specified in config.")
            print(f"QC for FULL LOAD of {bronze_table_full_entity_name} bronze table data. Fetching today's data from all layers...")        
            landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
            return landing_data, raw_data, bronze_data
            
    elif source_datasource_type == 'file':
        print("Source type 'file' is not fully implemented for data fetching in this script.")
        return None, None, None # Return None if not implemented
    else:
        print("Some unknown source type")
        return None, None, None # Return None for unknown source types


# Helper functions for data manipulation and hashing
def convert_null(col_obj: Column) -> Column:
    """
    Converts null values in a column to the string 'NULL'.
    """
    return F.when(col_obj.eqNullSafe(None), F.lit('NULL')).otherwise(col_obj)

def column_cast(field: T.StructField):
    """
    Casts the column of a DataFrame based on its data type to a string representation
    suitable for hashing.
    """
    col_name, col_type = (field.name, field.dataType)
    # Convert timestamp to epoch in string
    if isinstance(col_type, T.TimestampType):
        str_col = F.col(col_name).cast('long').cast('string')
    # Convert boolean to string value 0 or 1
    elif isinstance(col_type, T.BooleanType):
        str_col = (
            F.when(F.col(col_name).eqNullSafe(True), F.lit('1'))
            .when(F.col(col_name).eqNullSafe(False), F.lit('0'))
            .otherwise(F.lit(None))
            .cast('string')
        )
    # Skip conversion for string type
    elif isinstance(col_type, T.StringType):
        str_col = F.col(col_name)
    # Convert all other types to string
    else:
        str_col = F.col(col_name).cast('string')
    
    return convert_null(str_col).alias(col_name)

def add_hash_key(df: DataFrame, pk_columns: list) -> DataFrame:
    """
    Adds 'pac_hash_key' (based on primary keys) and 'pac_hash_key_non_pk' (based on all columns)
    to the DataFrame for comparison purposes.
    """
    all_columns = df.schema.fields  # Get StructField objects
    
    # Apply hash key for primary key columns
    if pk_columns:
        df = df.withColumn(
            'pac_hash_key',
            F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns if field.name in pk_columns]))
        )
    else:
        # If no primary keys, apply hash key for ALL columns for 'pac_hash_key' as well
        df = df.withColumn(
            'pac_hash_key',
            F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns]))
        )
    
    # Always apply hash key for ALL columns for 'pac_hash_key_non_pk'
    df = df.withColumn(
        'pac_hash_key_non_pk',
        F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns]))
    )
    
    return df

# COMMAND ----------

# DBTITLE 1,checks and write to table functions
# Count and Subtract Checks (Modified to return metrics)
def run_countcheck_new(todays_landing_data_with_hash, todays_bronze_data, landing_table_full_entity_name):
    """
    Performs a count check between landing and bronze data.
    Returns a tuple: (status_bool, landing_count, bronze_count)
    """
    todays_landing_data_with_hash_count = todays_landing_data_with_hash.count()
    todays_bronze_data_count = todays_bronze_data.count()
    
    print("------ COUNT CHECK STARTS --------")
    print(f"Table: {landing_table_full_entity_name}")
    print("LANDING count = ", todays_landing_data_with_hash_count)
    print("BRONZE count = ", todays_bronze_data_count)

    if todays_landing_data_with_hash_count != todays_bronze_data_count:
        print("CAUTION, landing count doesn't match with bronze count!!! Please check!")
        count_check_status = False
    else:
        print("All good, landing count matches with bronze count")
        count_check_status = True
    print("------ COUNT CHECK ENDS --------\n")
    return count_check_status, todays_landing_data_with_hash_count, todays_bronze_data_count

def run_subtractall_new(todays_landing_data_with_hash, todays_bronze_data, landing_table_full_entity_name):    
    """
    Performs a subtract check to identify rows present in one DataFrame but not the other.
    Returns a tuple: (missing_from_landing_count, missing_from_bronze_count, subtract_status_bool)
    """
    hash_columns_for_comparision = ['pac_hash_key', 'pac_hash_key_non_pk']
    todays_landing_data_with_hash_for_comparision = todays_landing_data_with_hash.select(*hash_columns_for_comparision)
    todays_bronze_data_for_comparision  = todays_bronze_data.select(*hash_columns_for_comparision)

    print("------ SUBTRACT CHECK STARTS --------")
    ##### COMMENTING LANDING-SUBTRACT-BRONZE ########
    print(f"Table: {landing_table_full_entity_name}")

    ###  LANDING SUBTRACT BRONZE ###
    # Default value if landing-to-bronze check is not active
    landing_subtract_bronze_status = True
    missing_from_landing_count = "NA"

    if ifLandingToBronzeCheckActive:
        print("-----###  LANDING SUBTRACT BRONZE STARTS ###-----")
        df_landing_subtract_bronze = todays_landing_data_with_hash_for_comparision.subtract(todays_bronze_data_for_comparision)
        missing_from_landing_count = df_landing_subtract_bronze.count()
        if missing_from_landing_count > 0:
            print("CAUTION - Data missing in bronze, but present in landing layer.")
            # Re-join to get the full rows for missing data (only display, don't store the full DF in return for simplicity)
            # missing_data_from_landing_df = todays_landing_data_with_hash.join(df_landing_subtract_bronze, on=hash_columns_for_comparision, how='inner').drop(*hash_columns_for_comparision)
            # display(missing_data_from_landing_df)
            # print(f"Rows present in landing data but not in bronze data for {landing_table_full_entity_name}. Please check the missing data above.")
            landing_subtract_bronze_status = False
            print("-----###  LANDING SUBTRACT BRONZE ENDS ###-----")
        else:
            print(f"All rows loaded successfully from landing to bronze for table {landing_table_full_entity_name}\n")
            print("-----###  LANDING SUBTRACT BRONZE ENDS ###-----")    
    

    print("-----###  BRONZE SUBTRACT LANDING STARTS ###-----") #(Always Executed)
    bronze_subtract_landing_status = True
    df_bronze_subtract_landing = todays_bronze_data_for_comparision.subtract(todays_landing_data_with_hash_for_comparision)
    missing_from_bronze_count = df_bronze_subtract_landing.count()

    if missing_from_bronze_count > 0:
        print("CAUTION - Data missing in landing, but present in bronze layer.")
        # # Re-join to get the full rows for missing data
        # missing_data_from_bronze_df = todays_bronze_data.join(df_bronze_subtract_landing, on=hash_columns_for_comparision, how='inner').select(*[col for col in todays_bronze_data.columns])
        # display(missing_data_from_bronze_df)
        # print(f"Rows present in bronze data but not in landing data for {landing_table_full_entity_name}. Please check the missing data above.")
        bronze_subtract_landing_status = False
    else:
        print(f"All Bronze layer data present in landing layer, for table {landing_table_full_entity_name}")
    
    print("-----###  BRONZE SUBTRACT LANDING ENDS ###-----")

    subtract_status = bronze_subtract_landing_status  # Final status only depends on this
    print("------ SUBTRACT CHECK ENDS --------\n")
    
    return missing_from_landing_count, missing_from_bronze_count, subtract_status

def run_checks(todays_landing_data_with_hash, todays_bronze_data, landing_table_full_entity_name):
    """
    Runs the count check and then the subtractall check.
    Returns all QC metrics: (landing_count, bronze_count, missed_from_landing, missed_from_bronze, overall_status)
    """
    # Run the count check first
    count_check_status, landing_count, bronze_count = run_countcheck_new(todays_landing_data_with_hash, todays_bronze_data, landing_table_full_entity_name)

    print("Running subtractall function to identify discrepancies.")
    missed_from_landing , missed_from_bronze, subtract_status = run_subtractall_new(todays_landing_data_with_hash, todays_bronze_data, landing_table_full_entity_name)
    return landing_count, bronze_count, missed_from_landing, missed_from_bronze, "SUCCESS" if subtract_status else "FAILED"

# Function to write QC results to Delta table
def write_qc_results(qc_results_table_full_name, run_id, source_table_name, bronze_table_name,watermark_column_name, 
                     source_table_count, bronze_table_count,
                     missed_records_landing, missed_records_bronze, status, created_at):
    
    """
    Writes a single row of QC results to a Delta table.
    If the table does not exist, it creates it.
    """
    
    qc_results_schema = T.StructType([
        T.StructField("run_id", T.StringType(), False),
        T.StructField("source_table_name", T.StringType(), False),
        T.StructField("bronze_table_name", T.StringType(), False),
        T.StructField("watermark_column_name", T.StringType(), False),
        T.StructField("source_table_count", T.StringType(), True),
        T.StructField("bronze_table_count", T.StringType(), True),
        T.StructField("missed_records_from_landing", T.StringType(), True),
        T.StructField("missed_records_from_bronze", T.StringType(), True),
        T.StructField("status", T.StringType(), False),
        T.StructField("created_at", T.TimestampType(), False)
    ])

    # Create a single-row DataFrame for the current QC run
    # results_df = spark.createDataFrame([
    #     (run_id, source_table_name, bronze_table_name, source_table_count, 
    #      bronze_table_count, missed_records_landing, missed_records_bronze, 
    #      status, created_at)
    # ], schema=qc_results_schema)

    # results_df = spark.createDataFrame([
    #             (run_id, source_table_name, bronze_table_name, source_table_count, 
    #             bronze_table_count, missed_records_bronze, 
    #             status, created_at)
    #         ], schema=qc_results_schema)


    watermark_column_name =  "null" if watermark_column_name is None else watermark_column_name # to log it an Null in case of full load tables

    # Create a single-row DataFrame for the current QC run
    results_df = spark.createDataFrame([
        (run_id, 
        source_table_name, 
        bronze_table_name, 
        watermark_column_name,
        source_table_count, 
        bronze_table_count, 
        missed_records_landing, 
        missed_records_bronze, 
        status, 
        created_at)], schema=qc_results_schema
    )
    
    # return display(results_df)

    try:
        # Check if the table exists, if not, create it
        if not spark.catalog.tableExists(qc_results_table_full_name):
            print(f"QC results table '{qc_results_table_full_name}' does not exist. Creating it...")
            results_df.write.format("delta").mode("append").saveAsTable(qc_results_table_full_name)
            print(f"QC results table '{qc_results_table_full_name}' created and first record inserted.")
        else:
            # Append results to the existing table
            results_df.write.format("delta").mode("append").insertInto(qc_results_table_full_name)
            print(f"QC results for {source_table_name} written to {qc_results_table_full_name}.")
    except Exception as e:
        print(f"Error writing QC results for {source_table_name} to {qc_results_table_full_name}: {e}")

# COMMAND ----------

# DBTITLE 1,list of table to run - 165
tables =  [
    "tblCompanies",
    "tblMobileNews",
    "tblVPReplaceDivisionContact",
    "tblEmployeeRoleCode",
    "tblEventMaster",
    "tblFile",
    "tblFileItem",
    "tblInstructionTypes",
    "tblItems_Phrase_Other_History",
    "tblItemsHistory",
    "tblMediaFileStatus",
    "tblPaymentType",
    "tblRanking",
    "tblSurveyTemplate",
    "tblVPDocument",
    "tblVPVendorDocument",
    "tblAgreementApprovalStatus",
    "tblBusinessType",
    "tblCostcoVendors",
    "tblEmployeeStatus",
    "tblEventChargeTypes",
    "tblForms",
    "tblLineofBusinessRates",
    "tblNotificationTypes",
    "tblPaperwork",
    "tblPaperworkVersion",
    "tblPriority",
    "tblRatingTypes",
    "tblRecipientTypes",
    "tblShiftType",
    "tblSurveyCategory",
    "tblActions",
    "tblAnswerSet",
    "tblContactRole",
    "tblContactTypes",
    "tblCookingSkills",
    "tblEmpStaffingTypes",
    "tblIssuesNotes",
    "tblUserTypes",
    "tblVendorTypes",
    "tblVPApprovalRecordTypes",
    "tblVPContactType",
    "tblBillCycleTypes",
    "tblDemoKitFee",
    "tblDemoKitLateFee",
    "tblDemoSource",
    "tblEmployeeRole",
    "tblItemAttributeMaster",
    "tblSASchedules",
    "tblServiceTypeSupplyMapping",
    "tblSupplies",
    "tblVendorInfoStatesList",
    "tblVPApproveVendorPartneringStatus",
    "tblLineofBusiness",
    "tblQuestionTemplate",
    "tblServiceTab",
    "tblVPApproveContactDivisions",
    "tblVPVendorGroups",
    "tblChargeType",
    "tblStatusCodes",
    "tblSurveyDomain",
    "tblVPApprovalStatus",
    "tblAbsenceReasons",
    "tblDemoStatusCode",
    "tblItemDelivery",
    "tblSupplierTypes",
    "tblARTransactionType",
    "tblIssueTypes",
    "tblLOBbillingcyclemapping",
    "tblDemoRateTypes",
    "tblWeather",
    "tblUserGroupMapping",
    "tblDemoGroupStatus",
    "tblMileageRates",
    "tblServiceTypePhrase",
    "tblServiceTypes",
    "dtproperties",
    "tblEmployeeCategory",
    "tblDemoType",
    "tblServiceType",
    "tblEquipments",
    "tblScheduledHours",
    "tblAnswer",
    "tblMediaFile",
    "tblServiceInstructionTypeMapping",
    "tblCancelCodes",
    "tblLOBEmpTypeMapping",
    "tblAuditInvoice",
    "tblVersion",
    "tblLOBServiceTypeMapping",
    "tblServiceTypeTabMapping",
    "tblEmployeeType",
    "tblBuyerDepartment",
    "tblItemDepartment",
    "tblPeriodMapping",
    "tblOtherEquipments",
    "tblState",
    "tblCompanyMessage",
    "tblJournalAccounts",
    "tblHelpMessages",
    "tblGroups",
    "tblWERJournals",
    "tblVPApproveEquipmentJoin",
    "tblCOA",
    "DataModificationLog",
    "tblVPVendorComments",
    "tblOfficersName",
    "tblVendorInfoDivisions",
    "tblVPApproveVendorDivisions",
    "tblDemoCount",
    "tblLOBVendorMapping",
    "tblVPApproveOtherEquipmentJoin",
    "tblApproveVendorDivisionContactMapping",
    "tblDirectBillJournals",
    "tblDemoRates",
    "tblVendorInfoStates",
    "tblVendorDivisions",
    "tblMobileEventEmployeeRecapReassignment",
    "tblIssues",
    "tblVPVendorUserJoin",
    "tblEmployeeLocations",
    "tblSAConfirmStatus",
    "tblVendorAgreement",
    "tblDemoRateDetails",
    "tblVendorDivisionContactMapping",
    "cntCreditDebitID",
    "tblAdjustments",
    "tblEquipmentList",
    "tblMobileSyncStatusItems",
    "tblMobileDevices",
    "tblCoupons",
    "tblActionGroupsJoin",
    "tblDirectBill",
    "tblCouponsHistory",
    "tblDirectBillDetail",
    "tblWERHeader",
    "tblEquipmentJoin",
    "tblVPVendorActionGroupsJoin",
    "tblDemoGroups",
    "tblPaymentMaster",
    "tblItems",
    "tblItems_Phrase_Other",
    "tblInvoice",
    "tblWERMileageWorkSheet",
    "tblInvoiceHistory",
    "tblProductLinks",
    "tblVPApprovalComments",
    "tblMobileSyncStatusCD",
    "tblVPApproveCoupons",
    "tblMobileSyncStatusEmployees",
    "tblOtherEquipmentJoin",
    "tblVPVendorDemos",
    "tblMobileBarCode",
    "tblStoreDateInfo",
    "tblWeatherHdr",
    "tblVPVendorDemoItemJoin",
    "tblMobileEventRecapInfo",
    "tblMobileEventEmployeeRecap",
    "tblDemoSalesAdvisors",
    "tblMobileRecapEventExpenses",
    "tblSurveyRespondent",
    "tblMobileRecapItemExpenses",
    "tblMobileEventItemRecapInfo",
    "tblWeatherForecastSimple",
    "tblEmployeeAvailability",
    "tblResponse_Temp",
    "tblResponse",
    "tblSurveyResponse",
    "tblWeatherForecastTxt",
    "tblBillingHeader",
    "tblVPVendorDemosHistory",
    "tblBreakers",
    "tblProducts",
    "tblDemos",
    "tblVPVendorDemoItemJoinHistory",
    "tblDemoItemJoin",
    "tblBillingDetail"
]

# COMMAND ----------

# DBTITLE 1,prepare paths - new
def get_json_file_paths(config_files_directory: str, tables: Optional[List[str]] = None, verbose: bool = True) -> List[str]:
    """
    Returns JSON file paths from the given directory, either matching the given table names (case-insensitive)
    or all JSON files if no tables are provided.

    Parameters:
        config_files_directory (str): Full path to the config files directory.
        tables (Optional[List[str]]): List of table names to match (without .json extension). Optional.
        verbose (bool): If True, prints debug information.

    Returns:
        List[str]: List of full file paths that matched.
    """
    
    # Step 1: List all files in the directory
    try:
        all_files = os.listdir(config_files_directory)
        if verbose:
            print("Total files present in directory:", len(all_files))
    except Exception as e:
        print("Error accessing directory:", e)
        return []

    # Step 2: Create a case-insensitive lookup dictionary
    file_lookup = {f.lower(): f for f in all_files}

    # Step 3: Build list of matched file paths
    json_files_path_list = []

    # Process only for selected tables written in list called "tables"
    if tables:
        for table in tables:
            target_filename = table.lower() + ".json"
            matched_file = file_lookup.get(target_filename)
            if matched_file:
                full_path = os.path.join(config_files_directory, matched_file)
                json_files_path_list.append(full_path)
            else:
                if verbose:
                    print(f"Config file not found for table: {table}")
    else:
        # No tables provided, get all .json files in the given directory
        json_files_path_list = [
            os.path.join(config_files_directory, f)
            for f in all_files if f.lower().endswith(".json")
        ]
        if verbose:
            print(f" No tables list provided. Using all JSON files.")

    # Step 4: Print summary
    if verbose:
        print(f"\nTotal file paths for processing: {len(json_files_path_list)}. Matched file paths displayed below:")
        for f in json_files_path_list:
            print(f)

    return json_files_path_list

# COMMAND ----------

json_files_path_list = get_json_file_paths(config_files_directory, tables=tables)

# COMMAND ----------

# DBTITLE 1,Runner cell
# Main execution loop for multiple JSON files
if not json_files_path_list:
    print(f"No JSON files found in the directory: {config_files_directory}. Please ensure the path is correct and contains .json files.")
else:
    print(f"Found {len(json_files_path_list)} JSON configuration files in '{config_files_directory}'.")
    current_run_id = f"{datetime.now().strftime('%Y-%m-%d')}_{dbutils.widgets.get('data_source')}_{str(uuid.uuid4())}" 
    print("Running for run-id :- ",current_run_id, "\n\n")

    for json_file_path in json_files_path_list:
        created_at_timestamp = datetime.now() # Get current timestamp for each table
        # path_to_json = os.path.join(config_files_directory, json_file)
        print(f"\n--- Processing configuration file: {json_file_path} (Run ID: {current_run_id}) ---")

        # Initialize metrics for logging
        source_table_name_qc = "N/A"
        bronze_table_name_qc = "N/A"
        watermark_column_name = "N/A"
        landing_count_qc = 0
        bronze_count_qc = 0
        missed_from_landing_qc = 0
        missed_from_bronze_qc = 0
        qc_status = "FAILED - Config Error"  # Default status if config parsing fails

        try:
            # Get parameters from the current JSON file
            lan_to_raw_json_data, source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name, primary_keys_list,final_landing_column_list_to_select,final_column_list_to_select = get_query_params_from_config(json_file_path)

            # Proceed only if JSON parsing was successful and returned valid parameters
            if lan_to_raw_json_data and landing_table_full_entity_name: # Check a critical parameter to ensure successful parsing
                source_table_name_qc = landing_table_full_entity_name
                bronze_table_name_qc = bronze_table_full_entity_name
                print(f'\nStarting data validation for table defined in {json_file_path}...')
                
                # Fetch data for QC
                todays_landing_data, todays_raw_data, todays_bronze_data = fetch_data_for_qc(
                    source_datasource_type, 
                    landing_table_full_entity_name, 
                    raw_table_full_entity_name, 
                    bronze_table_full_entity_name, 
                    watermark_column_name, 
                    # ifCheckForFullLoad == 'True', # Ensure boolean conversion from widget string
                    ifCheckForFullLoad,
                    final_landing_column_list_to_select,
                    final_column_list_to_select
                )
                print("\n")

                # Perform checks if dataframes were successfully fetched
                if todays_landing_data is not None and todays_bronze_data is not None:
                    todays_landing_data_with_hash = add_hash_key(todays_landing_data, primary_keys_list)
                    
                    # Capture metrics from run_checks
                    landing_count_qc, bronze_count_qc, missed_from_landing_qc, missed_from_bronze_qc, qc_status = run_checks(
                        todays_landing_data_with_hash, 
                        todays_bronze_data, 
                        landing_table_full_entity_name
                    )

                    # landing_count_qc, bronze_count_qc, missed_from_bronze_qc, qc_status = run_checks(
                    #     todays_landing_data_with_hash, 
                    #     todays_bronze_data, 
                    #     landing_table_full_entity_name
                    # )

                else:
                    print(f"Skipping data validation for '{json_file_path}' due to an issue fetching dataframes. Check previous logs for errors.")
                    qc_status = "FAILED - Data Fetch Error"
            else:
                print(f"Skipping processing for '{json_file_path}' due to an error in fetching configuration parameters.")
                qc_status = "FAILED - Config Parse Error" # Update status for config parsing failure

        except Exception as e:
            print(f"An unexpected error occurred during processing of '{json_file_path}' : {e}")
            qc_status = f"FAILED - Unexpected Error: {str(e)[:200]}" # Truncate error message

        finally:
            # Always write results, even if there's an error, to log the attempt and status
            write_qc_results(
                qc_results_table_full_name,
                current_run_id,
                source_table_name_qc,
                bronze_table_name_qc,
                watermark_column_name,
                landing_count_qc,
                bronze_count_qc,
                missed_from_landing_qc,
                missed_from_bronze_qc,
                qc_status,
                created_at_timestamp
            )

# COMMAND ----------

# MAGIC %sql
# MAGIC -- select * from dnap_prod.default.qc_results;
# MAGIC -- select count(*) from dnap_prod.default.qc_results where run_id like "2025-05-27_CES_5_6dbb485b-645d-4ea2-bfe4-abbc0e87a361";
# MAGIC -- select * from dnap_prod.default.qc_results where run_id like "2025-05-27_CES_5_6dbb485b-645d-4ea2-bfe4-abbc0e87a361" --and watermark_column= "null";
# MAGIC -- delete from dnap_prod.default.qc_results where run_id = "2025-05-26_CES_5_5173fec7-dae9-45eb-bd37-ad658f830864"
# MAGIC
# MAGIC -- truncate table dnap_prod.default.qc_results