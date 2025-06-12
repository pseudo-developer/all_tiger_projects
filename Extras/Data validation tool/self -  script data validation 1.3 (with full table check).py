# Databricks notebook source
# MAGIC %md
# MAGIC ## Functional code

# COMMAND ----------

# dbutils.widgets.removeAll()

# COMMAND ----------

dbutils.widgets.text('config_file', '', label='Full file path to the Table Configuration file')
dbutils.widgets.text('ifCheckForFullLoad', '', label='Forced full load QC check for the table')

config_file_path = dbutils.widgets.get('config_file')
ifCheckForFullLoad = dbutils.widgets.get('ifCheckForFullLoad')

print("config_file_path : ", config_file_path)
print("ifCheckForFullLoad : ", ifCheckForFullLoad)

# COMMAND ----------

# DBTITLE 1,All necessary imports
from pyspark.sql.functions import *
import json

# COMMAND ----------

# DBTITLE 1,params function
def get_query_params_from_config(path_to_json):
    try:
        with open(path_to_json, 'r') as f:
            lan_to_raw_json_data = json.load(f)

        source_datasource_type = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['type']
        # print(source_datasource_type)

        #LANDING
        landing_catalog_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['catalog_name']
        landing_schema_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['schema_name']
        landing_table_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['data_store']['properties']['table_name']
        landing_table_full_entity_name = f"{landing_catalog_name}.{landing_schema_name}.{landing_table_name}"

        #RAW
        raw_catalog_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['catalog_name']
        raw_schema_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['schema_name']
        raw_table_name = lan_to_raw_json_data['source_to_target_definition']['target_definition']['data_store']['properties']['table_name']
        raw_table_full_entity_name = f"{raw_catalog_name}.{raw_schema_name}.{raw_table_name}"

        #BRONZE
        bronze_table_full_entity_name = lan_to_raw_json_data['source_to_target_definition']['table_transform']['cdc']['properties']['table_name_for_comparison']


        # ALIAS COLUMNS
        schema_transform_map_list = lan_to_raw_json_data['source_to_target_definition']['target_definition']['schema_transform_map']
        # print(schema_transform_map)
        # print(type(schema_transform_map))
        landing_columns_aliased = [col(item['source_column_name']).alias(item['column_name']) for item in schema_transform_map_list]
        # print(landing_columns_aliased)

        # OTHER INFO
        watermark_column_name = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['watermark_column']
        primary_keys_list = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['primary_keys']
        except_column_list = lan_to_raw_json_data['source_to_target_definition']['source_entity']['property']['except_column_list']

        final_landing_column_list_to_select = [col for col in landing_columns_aliased if col not in except_column_list]
        final_column_list_to_select = [col(item['column_name']) for item in schema_transform_map_list if col(item['column_name']) not in except_column_list]

        print(f"Params fetched from file {path_to_json} :-")
        # print("lan_to_raw_json_data:", lan_to_raw_json_data)
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
        print(f"An error occurred: {e}")

# COMMAND ----------

# path_to_json = '/Workspace/Shared/dnap-ingestion-framework01122024/landing_to_raw_definitions_demo_agency/tblBlackOutStoreDatesHistory.json'

# path_to_json = config_file_path
# lan_to_raw_json_data, source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name, primary_keys_list,final_landing_column_list_to_select , final_column_list_to_select = get_query_params_from_config(path_to_json)

# print(final_landing_column_list_to_select, "\n")
# print(final_column_list_to_select)

# COMMAND ----------

def get_second_max_version_bronze(bronze_table_full_entity_name):
    history_df = spark.sql(f"DESC HISTORY {bronze_table_full_entity_name}").where("operation = 'MERGE'").orderBy("version", ascending=False)    
    if history_df.count() >= 2:
        is_first_time_load = False
        # second_max_version_bronze = history_df.collect()[1]['version']
        second_max_version_bronze = history_df.select('version').take(2)[1]['version']
        print("second_max_version_bronze is : ",second_max_version_bronze)
    else:
        is_first_time_load = True
        second_max_version_bronze = None  # history_df.select('version').first()['version']
    
    return second_max_version_bronze, is_first_time_load

# COMMAND ----------

def get_max_prev_watermark_value_bronze(bronze_table_full_entity_name, watermark_column_name,second_max_version_bronze) -> int:
    if spark.catalog.tableExists(bronze_table_full_entity_name):
        if watermark_column_name:
            max_prev_watermark_value_bronze = spark.sql(f"""
                SELECT MAX({watermark_column_name}) AS max_watermark_value FROM (
                    select * from {bronze_table_full_entity_name} version as of {second_max_version_bronze}
                )
            """).collect()[0][0]
            print("max_prev_watermark_value_bronze is :",max_prev_watermark_value_bronze)
            return max_prev_watermark_value_bronze
        else:
            print(f"watermark column {watermark_column_name} does not exist in {bronze_table_full_entity_name}")
    else:
        print(f"Table {bronze_table_full_entity_name} does not exist. Hence this is first time load of the table")

# COMMAND ----------

def run_countcheck(todays_landing_data, todays_bronze_data):
    try:
        todays_landing_data_count = todays_landing_data.count()
        todays_bronze_data_count = todays_bronze_data.count()
        print("------ COUNT CHECK STARTS --------")
        print("LANDING count = ", todays_landing_data_count)
        print("BRONZE count = ", todays_bronze_data_count)
        if todays_landing_data_count != todays_bronze_data_count:
            raise ValueError("CAUTION, landing count doesn't match with bronze count!!! Please check")
        else:
            print("All good, landing count matches with bronze count")
        print("------ COUNT CHECK ENDS --------\n")
    except Exception as e:
        print(f"An error occurred during the count check: {e}")

def run_exceptall(todays_landing_data, todays_bronze_data):
    # Ensure both DataFrames have the same columns and data types
    landing_columns = [col(c).cast("string") for c in todays_landing_data.columns]
    bronze_columns = [col(c).cast("string") for c in todays_bronze_data.columns]

    todays_landing_data_casted = todays_landing_data.select(*landing_columns)
    todays_bronze_data_casted = todays_bronze_data.select(*bronze_columns)

    # Use exceptAll to find rows in landing data that are not in bronze data
    # df_landing_except_bronze = todays_landing_data_casted.exceptAll(todays_bronze_data_casted)
    # df_bronze_except_landing = todays_bronze_data_casted.exceptAll(todays_landing_data_casted)

    df_landing_except_bronze = todays_landing_data_casted.subtract(todays_bronze_data_casted)
    df_bronze_except_landing = todays_bronze_data_casted.subtract(todays_landing_data_casted)

    print("------ EXCEPT CHECK STARTS --------")
    print("1. LANDING EXCEPT BRONZE")
    if df_landing_except_bronze.count() > 0:
        print("CAUTION - Number of rows that are present in todays_landing_data but not in todays_bronze_data :", df_landing_except_bronze.count(), ". Missing data is displayed below")
        display(df_landing_except_bronze)
        raise ValueError("Rows present in landing data but not in bronze data. Please check the missing data above.")
    else:
        print(f"All rows loaded successfully from landing to bronze for table {landing_table_full_entity_name}\n")

    print("2. BRONZE EXCEPT LANDING")
    if df_bronze_except_landing.count() > 0:
        print("CAUTION - Number of rows that are present in todays_bronze_data but not in todays_landing_data :", df_bronze_except_landing.count(), ". Missing data is displayed below")
        display(df_bronze_except_landing)
        raise ValueError("Rows present in bronze data but not in landing data. Please check the missing data above.")
    else:
        print(f"All rows loaded successfully from landing to bronze for table {landing_table_full_entity_name}")

    print("------ EXCEPT CHECK ENDS --------\n")

# COMMAND ----------

# DBTITLE 1,fetch data
def fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select):
    landing_data = spark.table(landing_table_full_entity_name).select([*final_landing_column_list_to_select])
    raw_data = spark.table(raw_table_full_entity_name).select([*final_column_list_to_select])
    bronze_data = spark.table(bronze_table_full_entity_name).where(col('__END_AT').isNull()).select([*final_column_list_to_select])
    return landing_data, raw_data, bronze_data

def fetch_incremental_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,watermark_column_name : None, second_max_version_bronze):
    max_prev_watermark_value_bronze = get_max_prev_watermark_value_bronze(bronze_table_full_entity_name, watermark_column_name,second_max_version_bronze)

    landing_data = spark.table(landing_table_full_entity_name).select([*final_landing_column_list_to_select]).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    raw_data = spark.table(raw_table_full_entity_name).select([*final_column_list_to_select]).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    bronze_data = spark.table(bronze_table_full_entity_name).where(col('__END_AT').isNull()).select([*final_column_list_to_select]).where(f"{watermark_column_name} > '{max_prev_watermark_value_bronze}'")
    
    return landing_data, raw_data, bronze_data


def fetch_data_for_qc(source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name : None, ifCheckForFullLoad : bool = False):
    if source_datasource_type == 'catalog':
        if watermark_column_name:
            print(f"Watermark column exists : `{watermark_column_name}`")

            if ifCheckForFullLoad:
                print("FORCED QC check for FULL LOAD of Incremental bronze table {bronze_table_full_entity_name} data. Fetching today's data from all layers...")
                landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
                return landing_data, raw_data, bronze_data

            second_max_version_bronze, is_first_time_load = get_second_max_version_bronze(bronze_table_full_entity_name)
            if is_first_time_load:
                print("FIRST TIME LOAD of Incremental bronze table {bronze_table_full_entity_name} data. Fetching today's data from all layers...")
                landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
                return landing_data, raw_data, bronze_data
            else:
                print("NOT first time load of this Incremental bronze table data. Fetching today's data from all layers...")
                landing_data, raw_data, bronze_data = fetch_incremental_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,watermark_column_name,second_max_version_bronze)
                return landing_data, raw_data, bronze_data

        else:
            print("Watermark column DOES NOT exist")
            print(f"QC for FULL LOAD of {bronze_table_full_entity_name} bronze table data. Fetching today's data from all layers...")            
            landing_data, raw_data, bronze_data = fetch_full_table_data(landing_table_full_entity_name,raw_table_full_entity_name,bronze_table_full_entity_name,final_landing_column_list_to_select,final_column_list_to_select)
            return landing_data, raw_data, bronze_data
        
    elif source_datasource_type == 'file':
        pass
    else:
        print("Some unknown source type")

# COMMAND ----------

def run():
    if __name__ == '__main__':
        # test_watermark_path_to_json = '/Workspace/Shared/MassIngestion_DataValidation/Anirudh/test_jsons/landing_to_raw/test_watermark.json'
        # path_to_json = test_watermark_path_to_json

        # path_to_json = '/Workspace/Shared/dnap-ingestion-framework01122024/landing_to_raw_definitions_demand_planning/ProductPriceList.json'

        path_to_json = config_file_path

        lan_to_raw_json_data, source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name, primary_keys_list,final_landing_column_list_to_select,  final_column_list_to_select = get_query_params_from_config(path_to_json)

        print('\nStarting the data validation...')
        todays_landing_data, todays_raw_data, todays_bronze_data = fetch_data_for_qc(source_datasource_type, landing_table_full_entity_name, raw_table_full_entity_name, bronze_table_full_entity_name, watermark_column_name, ifCheckForFullLoad)
        print("\n")
        
        try:
            run_countcheck(todays_landing_data, todays_bronze_data)
            run_exceptall(todays_landing_data, todays_bronze_data)
        except ValueError as e:
            print(f"Data validation failed during count check: {e}")
            raise

# COMMAND ----------

run()