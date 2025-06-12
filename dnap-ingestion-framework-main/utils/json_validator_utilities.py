# Import necessary libraries
import os, sys, json, re, ast
from pydantic import BaseModel, ValidationError, validator, root_validator, model_validator, field_validator, ValidationInfo
from typing import List, Optional
import pyspark.sql.types as T
from pyspark.sql import functions as F
from utils.helper import *

def load_json_file(file_path: str):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            print("JSON file is valid and successfully parsed.")
            return data
    except Exception as e:
        raise ValueError(f"Invalid JSON file. Error: {e}")

def validate_properties(cls, v):
    
        required_keys = {'catalog_name', 'schema_name', 'table_name'}   

        # Ensure all required keys are present
        if not required_keys.issubset(v.keys()):
            raise ValueError(f"Missing required keys in data_store properties: {required_keys - v.keys()}")

        # Naming convention validation
        for key in required_keys:
            if not re.match(r'^[A-Za-z0-9_-]+$', v[key]):
                raise ValueError(f" {key} contains invalid characters or spaces")       
        return v
 
def validate_source_properties_columns(cls, model):
        target_schema_columnss = {col.column_name for col in model.target_definition.schema_transform_map}
        
        # Check primary_key column list
        for primary_key_col in model.source_entity.property.primary_keys:
            if primary_key_col not in target_schema_columnss:
                raise ValueError(f"Primary key column {primary_key_col} not found in target schema columns.")
    
        # Check watermark column
        if model.source_entity.property.watermark_column and model.source_entity.property.watermark_column not in target_schema_columnss:
            raise ValueError(f"Watermark column '{model.source_entity.property.watermark_column}' is not in schema columns: {target_schema_columnss}")

        # Check seq_col column list
        for seq_column in model.source_entity.property.seq_col:
            if seq_column not in target_schema_columnss:
                raise ValueError(f"seq_col {seq_column} not found in target schema columns.")

        # Check except_column_list
        for except_column in model.source_entity.property.except_column_list:
            if except_column not in target_schema_columnss:
                raise ValueError(f"except_column_list {except_column} not found in target schema columns.")

        return model
    
def validate_expression(cls, v, source_column_name):
        if v == "":
            return v  # Allow empty strings as valid derived expressions

        # Check if the expression starts with 'F.'
        if not v.startswith("F."):
            raise ValueError(f"Invalid derived_expression: '{v}'. Must start with 'F.' for PySpark functions.")

        # Syntax validation using ast
        try:
            parsed_expr = ast.parse(v, mode='eval')  # Parse in 'eval' mode
        except SyntaxError as e:
            raise ValueError(f"Invalid derived_expression: '{v}'. Syntax error: {e}")

        # Ensure the expression is a valid PySpark function
        valid_functions = dir(F)  # Get the list of available PySpark functions
        root_node = parsed_expr.body

        if isinstance(root_node, ast.Call):  # Check if it's a function call
            function_name = (
                root_node.func.attr if isinstance(root_node.func, ast.Attribute) else None
            )
            if not function_name or function_name not in valid_functions:
                raise ValueError(
                    f"Invalid derived_expression: '{v}'. '{function_name}' is not a valid PySpark function."
                )
        else:
            raise ValueError(f"Invalid derived_expression: '{v}'. Must be a function call.") 

        # Additional check for source_column_name when derived_expression is not empty
        if v != "" and source_column_name == "":
            raise ValueError("source_column_name cannot be empty when derived_expression is not empty.")

        return v
    
def validate_partition_cluster_flag(cls, value):
        # Validate that partition_cluster_flag has a valid value
        valid_values = ["liquid", "partition", ""]
        if value not in valid_values:
            raise ValueError(f"Invalid partition_cluster_flag: '{value}'. Must be one of {valid_values}.")
        return value
    
def validate_partition_col_for_liquid_flag(cls, values):
        partition_cluster_flag = values.partition_cluster_flag
        partition_col = values.partition_col

        # If partition_cluster_flag is "liquid", check partition_col length
        if partition_cluster_flag == "liquid" and len(partition_col) > 4:
            raise ValueError(
                f"When partition_cluster_flag is 'liquid', partition_col must have less than or equal to 4 values. "
                f"Got {len(partition_col)} values instead."
            )
        return values
    
def validate_target_properties_columns(cls, model):
        target_schema_columns = {col.column_name for col in model.schema_transform_map}
        
        # Check primary_key column list
        for primary_key_col in model.property.primary_keys:
            if primary_key_col not in target_schema_columns:
                raise ValueError(f"Primary key column {primary_key_col} not found in target schema columns.")
    
        # Check seq_col column list
        for seq_column in model.property.seq_col:
            if seq_column not in target_schema_columns:
                raise ValueError(f"Primary key column {seq_column} not found in target schema columns.")

        # Check partition_col column list
        for partition_column in model.property.partition_col:
            if partition_column not in target_schema_columns:
                raise ValueError(f"Primary key column {partition_column} not found in target schema columns.")
        return model
    
def validate_load_strategy(cls, v):
        valid_modes = ['cdc append', 'SCD_1', 'SCD_2']
        if v.get('mode') not in valid_modes:
            raise ValueError(f"Invalid load strategy mode. Expected one of: {valid_modes}")
        return v
    
def validate_cdc_components(cls, v):
        # Check if 'enabled' key exists and validate its type
        if 'enabled' not in v:
            raise ValueError("The 'cdc' dictionary must contain the 'enabled' key.")
        if not isinstance(v['enabled'], bool):
            raise ValueError("The 'enabled' value in cdc must be a boolean.")

        # Check 'table_name_for_comparison' format
        table_name = v.get('properties', {}).get('table_name_for_comparison', '')
        if not table_name:
            raise ValueError("CDC 'table_name_for_comparison' is missing.")

        # Validate format: catalog.schema.table
        if not re.match(r'^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$', table_name):
            raise ValueError(
                f"Invalid 'table_name_for_comparison' format: '{table_name}'. "
                "Expected format: catalog.schema.table with only alphanumeric characters and underscores."
            )
        return v
    
def validate_target_schema_source_columns(cls, model):
        source_schema_columns = {col.column_name for col in model.source_entity.schema}

        for transform_map in model.target_definition.schema_transform_map:
            if transform_map.source_column_name not in source_schema_columns:
                raise ValueError(
                    f"source_column_name '{transform_map.source_column_name}' in SchemaTransformMap "
                    f"is not present in source schema columns: {source_schema_columns}"
                )

        return model
    
def create_target_table_if_enabled(json_data):
    # Extract target definition
    target_definition = json_data['source_to_target_definition']['target_definition']
    catalog = target_definition['data_store']['properties']['catalog_name']
    schema = target_definition['data_store']['properties']['schema_name']
    table = target_definition['data_store']['properties']['table_name']
    schema_transform_map = target_definition['schema_transform_map']
    
    # Construct the table name
    full_table_name = f"{catalog}.{schema}.{table}"

    # Check if the table already exists
    if delta_table_exists(full_table_name):
        raise Exception(f"Table '{full_table_name}' already exists.")

    # Generate the column definitions for the CREATE TABLE statement
    column_definitions = []
    for col in schema_transform_map:
        spark_type = get_spark_type(col['type'])  # Convert to Spark data type
        type_str = spark_type.simpleString()  # Get the Spark SQL string for the type
        column_definitions.append(f"  {col['column_name']} {type_str.upper()}")

    # Join column definitions with commas
    column_definitions_str = ",\n".join(column_definitions)

    # Define table properties
    table_properties = """
        TBLPROPERTIES (
        'delta.enableDeletionVectors' = 'true',
        'delta.feature.appendOnly' = 'supported',
        'delta.feature.deletionVectors' = 'supported',
        'delta.feature.invariants' = 'supported',
        'delta.minReaderVersion' = '3',
        'delta.minWriterVersion' = '7'
        )"""

    # Construct the CREATE TABLE statement
    create_table_query = f"""
        CREATE TABLE {full_table_name} (
        {column_definitions_str}
        )
        USING delta
        {table_properties};
        """

    # Print the table creation script
    print("Generated CREATE TABLE Script:")
    print(create_table_query)

    # Execute the CREATE TABLE script using Spark SQL
    spark.sql(create_table_query)

    print(f"Table '{full_table_name}' created successfully.")
