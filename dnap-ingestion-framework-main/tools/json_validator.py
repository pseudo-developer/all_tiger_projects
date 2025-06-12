# Databricks notebook source
# MAGIC %md
# MAGIC Databricks Notebook: JSON Validation using Pydantic

# COMMAND ----------

# Import necessary libraries
import os, sys, json, re, ast
from pydantic import BaseModel, ValidationError, validator, root_validator, model_validator, field_validator, ValidationInfo
from typing import List, Optional
import pyspark.sql.types as T
from pyspark.sql import functions as F

# COMMAND ----------

# Widgets for interactive inputs
dbutils.widgets.dropdown("create_table", "N", ["Y", "N"], "Create Table? (Y/N)")
dbutils.widgets.text("configuration_path", "", "Enter JSON File Path")
dbutils.widgets.text('utils_path', '', label='Path to the Ingestion Framework Utils module')

# COMMAND ----------

sys.path.append(os.path.abspath(dbutils.widgets.get('utils_path')+"/utils"))
from utils.helper import *
from utils.json_validator_utilities import *

# COMMAND ----------

# MAGIC %md
# MAGIC Source Validation

# COMMAND ----------

# Define a base model with strict validation
class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"  # Forbid extra keys

class SourceDataStore(StrictBaseModel):
    type: str
    properties: dict
    
    @field_validator('properties')
    def validate_source_data_store_properties_field(cls, v):
        return validate_properties(cls, v)

class SchemaDefinition(StrictBaseModel):
    column_name: str
    data_type: str
    nullable: bool

class SourceProperties(StrictBaseModel):
    primary_keys: List[str] = []
    watermark_column: Optional[str] = None
    initial_watermark_value: Optional[str] = None
    seq_col: List[str] = []
    except_column_list: List[str] = []     

class SourceEntity(StrictBaseModel):
    data_store: SourceDataStore
    schema: List[SchemaDefinition]
    property: SourceProperties

# COMMAND ----------

# MAGIC %md
# MAGIC Target validation

# COMMAND ----------

class TargetDataStore(SourceDataStore):
    type: str
    properties: dict

class SchemaTransformMap(StrictBaseModel):
    column_name: str
    source_column_name: str
    type: str
    derived_expression: str

    @field_validator('derived_expression')
    def validate_derived_expression(cls, v, source_column_name):                
        return validate_expression(cls, v, source_column_name)

class TargetProperties(StrictBaseModel):
    primary_keys: List[str]
    seq_col: List[str]
    partition_cluster_flag: str
    partition_col: List[str]

    @field_validator('partition_cluster_flag')
    def check_partition_cluster_flag(cls, value):
        return validate_partition_cluster_flag(cls, value)

    @model_validator(mode='after')
    def check_partition_col_for_liquid_flag(cls, values):        
        return validate_partition_col_for_liquid_flag(cls, values)

class TargetDefinition(StrictBaseModel):
    data_store: TargetDataStore
    schema_transform_map: List[SchemaTransformMap]
    property: TargetProperties

    @model_validator(mode='after')
    def check_target_properties_columns(cls, model):
        return validate_target_properties_columns(cls, model)


# COMMAND ----------

# MAGIC %md
# MAGIC Some basic & logical validation

# COMMAND ----------

class TableTransform(StrictBaseModel):
    dedup: dict
    cdc: dict
    load_strategy: dict

    @field_validator('load_strategy')
    def check_load_strategy(cls, v):
        return validate_load_strategy(cls, v)

    @field_validator('cdc')
    def check_cdc_components(cls, v):
        return validate_cdc_components(cls, v)

class Rules(StrictBaseModel):
    bronze: dict

# COMMAND ----------

class SourceToTargetDefinition(StrictBaseModel):
    source_entity: SourceEntity
    target_definition: TargetDefinition
    table_transform: TableTransform
    rules: Rules

    # Validate each SchemaTransformMap's source_column_name is present in source schema
    @model_validator(mode='after')
    def check_target_schema_source_columns(cls, model):
        return validate_target_schema_source_columns(cls, model)

    # Validate each source_entity property's columns are present in column_name of schema_transform_map
    @model_validator(mode='after')
    def check_source_properties_columns(cls, model):
        return validate_source_properties_columns(cls, model)

# COMMAND ----------

class JSONValidator(StrictBaseModel):
    source_to_target_definition: SourceToTargetDefinition

# COMMAND ----------

#Validate JSON
def validate_json(json_data):
    try:
        validated_data = JSONValidator(**json_data)
        print("JSON Validation Successful.")
        return True
    except ValidationError as e:
        print("Validation Error:", e)
        return False

# COMMAND ----------

# Run Tests
file_path = dbutils.widgets.get("configuration_path")
if not file_path:
    raise ValueError('Invalid JSON file path.')
try:
    json_data = load_json_file(file_path)
    if validate_json(json_data):
        if dbutils.widgets.get("create_table") == 'Y':
            create_target_table_if_enabled(json_data)
except ValueError as e:
    print(e)
