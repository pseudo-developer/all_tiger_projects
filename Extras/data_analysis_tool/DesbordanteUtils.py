
import csv
import json
import os
import glob
import pandas as pd
from typing import List, Dict
from collections import Counter
from pyspark.sql import SparkSession

# Initialize a Spark session
spark = SparkSession.builder.appName("MySparkSession").getOrCreate()  # Get an existing session or create a new one

def is_valid_column_as_key(catalog: str, schema: str, table: str, column_str: str) -> bool:
    """
    Checks if a single or combination of columns (space-separated in `column_str`) 
    have no nulls and are unique when combined.
    """
    try:
        # Split in case of multiple column names provided in a single string
        columns = column_str.split()

        # Build query for required columns
        col_expr = ", ".join([f"`{col}`" for col in columns])
        df = spark.sql(f"SELECT {col_expr} FROM {catalog}.{schema}.{table}")

        # Check for nulls in any of the involved columns
        null_condition = " OR ".join([f"`{col}` IS NULL" for col in columns])
        null_count = df.filter(null_condition).count()

        # Check uniqueness across the combination of columns
        total_rows = df.count()
        distinct_rows = df.distinct().count()

        if null_count > 0 or distinct_rows < total_rows:
            return False
        return True

    except Exception as e:
        print(f"[WARN] Could not validate columns `{column_str}`: {str(e)}")
        return False

def detect_fds_from_df(df: pd.DataFrame) -> List[List[str]]:
    try:
        algo = desbordante.fd.algorithms.Default()
        algo.load_data(table=df)
        algo.execute()
        return [parse_fd_lhs(str(fd)) for fd in algo.get_fds()]
    except Exception as e:
        print(f"FD Error: {str(e)}")
        return []
    

def normalize_column_name(col: str) -> str:
    return col.strip().strip("[]")

def determine_best_identifier_by_fd_frequency(
    uccs: List[List[str]],
    fds: List[List[str]]
) -> List[List[str]]:
    # ✅ Step 1: Normalize FDs
    normalized_fds = [tuple(normalize_column_name(col) for col in fd) for fd in fds if fd]
    fd_lhs_counts = Counter(normalized_fds)

    # ✅ Step 2: Normalize UCCs
    normalized_uccs = [tuple(normalize_column_name(col) for col in ucc) for ucc in uccs]
    
    # ✅ Step 3: Score UCCs based on FD frequency
    ucc_frequencies = {
        ucc: fd_lhs_counts.get(ucc, 0) for ucc in normalized_uccs
    }

    if not ucc_frequencies:
        print("[INFO] No UCCs matched with FD LHS.")
        return []

    # ✅ Step 4: Return UCC(s) with highest frequency
    max_freq = max(ucc_frequencies.values())
    print(f"[INFO] Max FD frequency: {max_freq}")
    best_identifiers = [list(ucc) for ucc, freq in ucc_frequencies.items() if freq == max_freq]

    return best_identifiers



def parse_fd_lhs(fd_str: str) -> List[str]:
    # Handles FD format like: '[col1, col2] -> col3'
    if "->" not in fd_str:
        return []
    lhs = fd_str.split("->")[0].strip()
    # Remove brackets if present
    if lhs.startswith("[") and lhs.endswith("]"):
        lhs = lhs[1:-1]
    return [col.strip() for col in lhs.split(",") if col.strip()]



def parse_ucc_columns(ucc_str: str) -> List[str]:
    # Format: {A, B}
    return [col.strip() for col in ucc_str.strip("{} ").split(",") if col.strip()]


def detect_uccs_from_df(df: pd.DataFrame) -> List[List[str]]:
    try:
        ucc_algo = desbordante.ucc.algorithms.Default()
        ucc_algo.load_data(table=df)
        ucc_algo.execute()
        return [parse_ucc_columns(ucc.to_long_string()) for ucc in ucc_algo.get_uccs()]
    except Exception as e:
        print(f"UCC Error: {str(e)}")
        return []
    

def analyze_tables(catalog_name: str, schema_name: str, table_names: str) -> Dict:
    if table_names:
        table_list = [tbl.strip() for tbl in table_names.split(',')]
    else:
        table_df = spark.sql(f"SHOW TABLES IN {catalog_name}.{schema_name}")
        table_list = [row.tableName for row in table_df.collect()]

    analysis_result = {}

    for table_name in table_list:
        full_table_name = f"{catalog_name}.{schema_name}.{table_name}"
        try:
            print(f"[INFO] Reading Spark table: {full_table_name}")
            spark_df = spark.table(full_table_name)

            # ✅ Remove binary columns
            binary_cols = [field.name for field in spark_df.schema.fields if field.dataType.simpleString() == 'binary']
            if binary_cols:
                print(f"[INFO] Dropping binary columns: {binary_cols}")
                spark_df = spark_df.drop(*binary_cols)

            if spark_df.count() == 0:
                print(f"[INFO] Table {full_table_name} has no records. Skipping analysis.")
                analysis_result[table_name] = {
                    "UCC": [],
                    "PrimaryKey": [],
                    "Message": "Table has no records."
                }
                continue

            spark_df = spark_df.limit(100000)
            pandas_df = spark_df.toPandas()

            uccs = detect_uccs_from_df(pandas_df)

            fds = []
            selected_id = []

            primary_keys = []

            if len(uccs) == 1:
                # ✅ Only one UCC found
                print(f"[INFO] Only one UCC found for {table_name}.")
                selected_id = [uccs[0]]
                primary_keys = uccs[0]  # Use directly without checking validity
                message = "Only one unique value found; it is the primary key."
            else:
                # ✅ Multiple UCCs found
                fds = detect_fds_from_df(pandas_df)
                selected_id = determine_best_identifier_by_fd_frequency(uccs, fds)

                # Now validate selected UCC candidates
                valid_identifier_cols = []
                if selected_id:
                    flat_cols = [col.strip("[]") for sublist in selected_id for col in sublist]
                    for col in flat_cols:
                        if is_valid_column_as_key(catalog_name, schema_name, table_name, col):
                            valid_identifier_cols.append(col)

                primary_keys = valid_identifier_cols

                # ✅ Set message based on how many valid primary keys we found
                if len(primary_keys) == 1:
                    message = "Only one unique value found; it is the primary key."
                elif len(primary_keys) > 1:
                    message = "Manual intervention is required to find the best candidate for primary key."
                else:
                    message = "No valid primary key could be determined."

            analysis_result[table_name] = {
                "UCC": uccs,
                "PrimaryKey": primary_keys,
                "Message": message
            }

        except Exception as e:
            print(f"[ERROR] Failed to analyze {full_table_name}: {str(e)}")
            analysis_result[table_name] = {
                "UCC": [],
                "PrimaryKey": [],
                "Message": f"Error analyzing table {table_name}: {str(e)}"
            }

    return analysis_result
