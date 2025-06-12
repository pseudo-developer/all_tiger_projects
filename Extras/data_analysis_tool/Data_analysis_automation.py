# Databricks notebook source
# MAGIC %md
# MAGIC ### NOTE : clear the notebook state before each run

# COMMAND ----------

!pip install desbordante
!pip install Levenshtein

from DesbordanteUtils import *

# COMMAND ----------

# Creating text widgets for catalog, schema, and table names
dbutils.widgets.dropdown("operation", "Identify PK/CK column", ["Identify PK/CK column", "Identify watermark column"], "Operation Type")
dbutils.widgets.text("catalog_name", "your_catalog", "Catalog Name")
dbutils.widgets.text("schema_name", "your_schema", "Schema Name")
dbutils.widgets.text("table_name", "", "Table Name (optional)")

# COMMAND ----------

# Importing necessary libraries
from pyspark.sql.functions import col, to_timestamp, count, when, mean
from pyspark.sql.types import StructType, StructField, StringType, LongType, TimestampType
from itertools import combinations
import sys, re
from pyspark.sql import DataFrame


# COMMAND ----------

def get_catalog_connection_type(catalog_name : str) -> str:
    """
    Returns the connection type (e.g., SQLSERVER, MYSQL) for the catalog provided via the 'catalog_name' widget.
    If the catalog is not external or has no connection, returns 'delta' or 'unknown'.
    """
    try:
        # Step 1: Get the connection name from the catalog
        catalog_info = spark.sql(f"DESCRIBE CATALOG {catalog_name}").collect()
        connection_name = None

        for row in catalog_info:
            if row["info_name"] == "Connection Name":
                connection_name = row["info_value"]
                break

        if not connection_name:
            return "delta"  # Likely a native Delta Lake catalog

        # Step 2: Get the connection type from the connection
        connection_info = spark.sql(f"DESCRIBE CONNECTION {connection_name}").collect()

        for row in connection_info:
            if row["info_name"].lower() == "type":
                return row["info_value"]

        return "unknown"

    except Exception as e:
        return f"error: {str(e)}"


# COMMAND ----------

# DBTITLE 1,Primary_key For SQLSERVER
def get_sqlserver_primary_keys(catalog: str, schema: str, table: str = None) -> dict:
    """
    Retrieves primary key information from SQL Server information schema.
    
    Args:
        catalog (str): The catalog name
        schema (str): The schema name
        table (str, optional): The table name
    
    Returns:
        dict: Dictionary mapping table names to their primary key columns
    """
    try:
        query = f"""
        SELECT
            tc.TABLE_SCHEMA,
            upper(tc.table_name) as table_name,
            kc.column_name,
            CASE
                WHEN count(*) OVER (PARTITION BY tc.table_name) > 1 THEN 'Composite Primary Key'
                ELSE 'Primary Key'
            END AS key_type
        FROM
            {catalog}.information_schema.table_constraints AS tc
        JOIN
            {catalog}.information_schema.key_column_usage AS kc
            ON tc.constraint_name = kc.constraint_name
            AND tc.table_schema = kc.table_schema
            AND tc.table_name = kc.table_name
        WHERE
            tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = '{schema}'
            {f"AND upper(tc.table_name) = '{table.upper()}'" if table else ""}
        ORDER BY
            tc.table_name,
            kc.ordinal_position
        """
        
        result = spark.sql(query).collect()
        pk_dict = {}
        
        for row in result:
            table_name = row["table_name"]
            column_name = row["column_name"]
            if table_name not in pk_dict:
                pk_dict[table_name] = []
            pk_dict[table_name].append(column_name)
            
        return pk_dict
    
    except Exception:
        return {}

# COMMAND ----------


from datetime import datetime
import re
from pyspark.sql.functions import col, mean, max, lit
from pyspark.sql.types import TimestampType

def find_valid_timestamp_column(catalog: str, schema: str, table: str):
    full_table = f"{catalog}.{schema}.{table}"

    try:
        df = spark.table(full_table)
        total_rows = df.count()

        timestamp_pattern = re.compile(r'(creat|update|modif|add|last|effective|start|review|audit|demo|enter|insert|end|change|load|entry|posted|recorded)', re.IGNORECASE)
        candidate_columns = [
            field.name for field in df.schema.fields
            if isinstance(field.dataType, TimestampType) and timestamp_pattern.search(field.name)
        ]

        if not candidate_columns:
            return ['NA'], "No column found which is matching with priority column list. Hence manual intervention is needed"
        
        else:
            now = datetime.now()
            filter_candidate_columns = []
            for c in candidate_columns:
                if df.filter(col(c).isNull()).limit(1).count() == 0:
                    max_timestamp = df.select(max(col(c))).first()[0]
                    max_ts = to_timestamp(lit(max_timestamp)) if isinstance(max_timestamp, str) else max_timestamp
                    if max_ts and max_ts < now:
                        filter_candidate_columns.append(c)
            if len(filter_candidate_columns) == 1:
                return [filter_candidate_columns[0]], ""
            elif len(filter_candidate_columns) == 0:
                return ['NA'], "No valid timestamp columns found after evaluation."
            else:
                agg_exprs = [mean(col(c)).alias(f"{c}__mean") for c in filter_candidate_columns]
                stats_row = df.agg(*agg_exprs).first().asDict()
                highest_mean = None
                top_cols = []

                for c in filter_candidate_columns:
                    mean_val = stats_row.get(f"{c}__mean")
                    if mean_val is not None:
                        if highest_mean is None or mean_val > highest_mean:
                            highest_mean = mean_val
                            top_cols = [c]
                        elif mean_val == highest_mean:
                            top_cols.append(c)

                if top_cols:
                    if len(top_cols) == 1:
                        return [top_cols[0]], ""
                    else:
                        return ['NA'], f"Columns {', '.join(top_cols)} have the same highest mean timestamp: {highest_mean}. Manual inspection required."
                else:
                    return ['NA'], "No valid timestamp columns found after evaluation."

    except Exception as e:
        return f"An error occurred: {e}"

# COMMAND ----------

def analyze_table_metadata(catalog: str, schema: str, operation: str, table: str = None):
    result_schema = StructType([
        StructField("catalog", StringType()),
        StructField("schema", StringType()),
        StructField("table_name", StringType()),
        StructField("primary_key", StringType()),
        StructField("Unique_columns", StringType()),
        StructField("Error_msg_Pk_Ck", StringType()),
        StructField("watermark_column", StringType()),
        StructField("Error_msg_watermark", StringType()),
        StructField("record_count", LongType())
    ])

    connection_type = get_catalog_connection_type(catalog)

    def process_single_table(catalog: str, schema: str, table: str) -> DataFrame:
        full_table = f"{catalog}.{schema}.{table}"
        try:
            df = spark.table(full_table)
            total_rows = df.count()
            if total_rows == 0:
                print(f"Skipping {full_table}: 0 records")
                return spark.createDataFrame([], result_schema)

            if operation == "Identify PK/CK column" and connection_type.upper() == "SQLSERVER":
                print(f"{sno+1}. {str(datetime.now()).split('.')[0]}- fetching Pk/Ck column:{catalog}.{schema}.{table} -- " , end = '')
                pk_cols=get_sqlserver_primary_keys(catalog, schema, table).get(table.upper(), [])
                # pk_cols = pk_dict.get(table, [])                
                pk_str = ",".join(pk_cols) if pk_cols else "NA"
                row_data = (catalog, schema, table, pk_str,None, None, None,None, total_rows)
                if pk_str == "NA":
                  result_info = analyze_tables(catalog, schema, table)
                  pk_str = ', '.join(result_info[table]['PrimaryKey'])
                  ucc_str = ', '.join([item[0].strip('[]') for item in result_info[table]['UCC']])
                  row_data = (catalog, schema, table, pk_str, ucc_str, result_info[table]['Message'], None, None, total_rows)                
                    
            
            elif operation == "Identify PK/CK column" and connection_type.upper() != "SQLSERVER":
               result_info = analyze_tables(catalog, schema, table)
               pk_str = ', '.join(result_info[table]['PrimaryKey'])
               ucc_str = ', '.join([item[0].strip('[]') for item in result_info[table]['UCC']])
               row_data = (catalog, schema, table, pk_str, ucc_str, result_info[table]['Message'], None, None, total_rows)


            elif operation == "Identify watermark column" :
                print(f"{sno+1}. {str(datetime.now()).split('.')[0]}- fetching watermark column:{catalog}.{schema}.{table} -- " , end = '')
                watermark_cols, err_msg = find_valid_timestamp_column(catalog, schema, table)
                watermark_str = ", ".join(watermark_cols)   
                row_data = (catalog, schema, table, None, None, None, watermark_str, err_msg, total_rows)

            return spark.createDataFrame([row_data], result_schema)

        except Exception as e:
            print(e)
            print(f"Error processing {full_table}: not found")
            return spark.createDataFrame([], result_schema)

    if isinstance(table, str):
        if ',' in table:
            tables_to_process = [tbl.strip() for tbl in table.split(',')]
        else:
            tables_to_process = [table.strip()]
    elif isinstance(table, list):
        tables_to_process = [t.strip() for t in table]
    else:
        table_rows = spark.sql(f"SHOW TABLES IN {catalog}.{schema}" ).filter("isTemporary is false").collect()
        tables_to_process = [row["tableName"] for row in table_rows]
        

    rows = []
    print(tables_to_process)
    from datetime import datetime
    for sno, tbl in enumerate(tables_to_process):
        # print(f"{sno+1}. {str(datetime.now()).split('.')[0]} - Processing table: {tbl} -- " , end = '')
        # print(sno,'. ' +str(datetime.now()).split('.')[0],f" - Processing table: {tbl} -- " , end = '')
        df = process_single_table(catalog, schema, tbl)
        rows.extend(df.collect())
        print("Completed!")

    result_df = spark.createDataFrame(rows, result_schema)
    result_df.createOrReplaceTempView("table_metadata_updates")
    # Create a table of your own for testing
    results_path = "dnap_engineering_frameworks_dev.generic_dbo_raw.data_analysis_table"

    if operation == "Identify PK/CK column":
        merge_query = f"""
        MERGE INTO {results_path} AS target
        USING table_metadata_updates AS source
        ON target.catalog = source.catalog
         AND target.schema = source.schema
        AND target.table_name = source.table_name
        WHEN MATCHED THEN
        UPDATE SET 
            target.primary_key = source.primary_key,
            target.Error_msg_Pk_Ck = source.Error_msg_Pk_Ck,
            target.record_count = source.record_count
        WHEN NOT MATCHED THEN
            INSERT (catalog, schema, table_name, primary_key, Unique_columns, Error_msg_Pk_Ck, record_count)
            VALUES (source.catalog, source.schema, source.table_name, source.primary_key, source.Unique_columns, source.Error_msg_Pk_Ck, source.record_count)
    """

    else:
        merge_query = f"""
        MERGE INTO {results_path} AS target
        USING table_metadata_updates AS source
        ON target.catalog = source.catalog
           AND target.schema = source.schema
           AND target.table_name = source.table_name
        WHEN MATCHED THEN
          UPDATE SET target.watermark_column = source.watermark_column,
                     target.Error_msg_watermark = source.Error_msg_watermark,   
                     target.record_count = source.record_count
                     
        WHEN NOT MATCHED THEN
          INSERT (catalog, schema, table_name, watermark_column,Error_msg_watermark, record_count)
          VALUES (source.catalog, source.schema, source.table_name, source.watermark_column,
           source.Error_msg_watermark, source.record_count)
        """

    spark.sql(merge_query)
    return result_df


# COMMAND ----------

def main():
    """
    Main function to run the table metadata analysis based on selected operation.
    Uses dbutils widgets to get parameters in Databricks environment,
    with fallback defaults for local testing.
    """
    try:
        catalog_name = dbutils.widgets.get("catalog_name")
        schema_name = dbutils.widgets.get("schema_name")
        table_name = dbutils.widgets.get("table_name")  # Optional
        operation = dbutils.widgets.get("operation")    # Must be "primary_key" or "watermark"
    except NameError:
        # Local testing fallback
        catalog_name = "default_catalog"
        schema_name = "default_schema"
        table_name = None
        operation = "watermark"  # or "primary_key"

    # Validate inputs
    if not catalog_name or not schema_name or not operation:
        print("Error: Catalog, schema, and operation must be provided.")
        return

    # Run the analysis
    
    result_df = analyze_table_metadata(
        catalog=catalog_name,
        schema=schema_name,
        operation=operation,
        table=table_name if table_name else None
    )

    if result_df is None:
        print("No metadata extracted.")
        return

    # Display results
    try:
        display(result_df)
    except NameError:
        result_df.show()


# COMMAND ----------

if __name__ == "__main__":
    
    main() # Call the main function to execute the program



