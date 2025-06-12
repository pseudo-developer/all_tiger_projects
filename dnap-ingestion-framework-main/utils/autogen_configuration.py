import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import re
import pyspark.sql.types as T
from pyspark.sql.functions import col
from pyspark.sql import SparkSession

import os
import glob
from pyspark.sql.utils import AnalysisException
from typing import List, Dict, Union

@dataclass
class SourceDataStoreProperty:
    catalog_name: Dict[str, str]
    schema_name: str
    table_name: Optional[str] = None
    file_location: Optional[str] = None
    spark_options: Optional[Dict[str, str]] = field(default_factory=dict)

@dataclass
class TargetDataStoreProperty:
    catalog_name: Dict[str, str]
    schema_name: str
    table_name: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_interval: Optional[str] = None
    spark_options: Optional[Dict[str, str]] = field(default_factory=dict)    

@dataclass
class SourceDataStore:
    type: str
    properties: SourceDataStoreProperty

@dataclass
class TargetDataStore:
    type: str
    properties: TargetDataStoreProperty    

@dataclass
class Column:
    column_name: str
    data_type: str
    nullable: bool

@dataclass
class SourceEntityProperty:
    primary_keys: List[str]
    watermark_column: Optional[str] = None
    initial_watermark_value: Optional[str] = None
    seq_col: Optional[List[str]] = None
    except_column_list: Optional[List[str]] = None

@dataclass
class TargetEntityProperty:
    primary_keys: List[str]
    seq_col: Optional[List[str]] = None
    partition_cluster_flag: Optional[List[str]] = None
    partition_col: Optional[List[str]] = None

@dataclass
class SchemaTransformMap:
    column_name: str
    source_column_name: str
    type: str
    derived_expression: Optional[str] = ""

@dataclass
class SourceEntity:
    data_store: SourceDataStore
    schema: List[Column]
    property: SourceEntityProperty

@dataclass
class TargetEntity:
    data_store: TargetDataStore
    schema_transform_map: List[SchemaTransformMap]
    property: TargetEntityProperty

@dataclass
class DedupConfig:
    enabled: bool
    properties: Dict[str, List[str]]

@dataclass
class CdcConfig:
    enabled: bool
    properties: Dict[str, any]

@dataclass
class LoadStrategyConfig:
    stage_enabled: bool
    mode: str

@dataclass
class TableTransform:
    dedup: DedupConfig
    cdc: CdcConfig
    load_strategy: LoadStrategyConfig

@dataclass
class Rule:
    rule: str

@dataclass
class RuleType:
    literal: Rule
    derived: Optional[Rule] = None

@dataclass
class RulesConfig:
    Error: RuleType
    Warn: Optional[RuleType] = None

@dataclass
class Rules:
    bronze: RulesConfig

@dataclass
class SourceToTargetDefinition:
    source_entity: SourceEntity
    target_definition: TargetEntity
    table_transform: TableTransform
    rules: Rules

@dataclass
class PipelineConfig:
    source_to_target_definition: SourceToTargetDefinition

    @staticmethod
    def from_dict(data: Dict) -> 'PipelineConfig':
        # Handle source entity
        source_data = data.get('source_to_target_definition', {}).get('source_entity', {})

        # Simplify entity property handling: only include non-default values
        source_entity_property = source_data['property']
        
        # Build EntityProperty with non-default fields
        source_entity_property_filtered = {
            "primary_keys": source_entity_property.get("primary_keys", []),
            "watermark_column": source_entity_property.get("watermark_column", None),
            "initial_watermark_value": source_entity_property.get("initial_watermark_value", None),
            "seq_col": source_entity_property.get("seq_col", []),
            "except_column_list": source_entity_property.get("except_column_list", []),
        }

        # Remove fields that are still in their default value (None or empty)
        source_entity_property_filtered = {k: v for k, v in source_entity_property_filtered.items() if v not in [None, [], ""]}

        source_entity = SourceEntity(
            data_store=SourceDataStore(
                type=source_data['data_store']['type'],
                properties=SourceDataStoreProperty(
                    **{
                        key: value
                        for key, value in source_data['data_store']['properties'].items()
                    }
                )
            ),
            schema=[Column(**col) for col in source_data['schema']],
            property=SourceEntityProperty(**source_entity_property_filtered)
        )

        # Handle target entity
        target_data = data.get('source_to_target_definition', {}).get('target_definition', {})

        # Simplify target entity property handling: only include non-default values
        target_entity_property = target_data['property']
        
        # Build EntityProperty with non-default fields for target
        target_entity_property_filtered = {
            "primary_keys": target_entity_property.get("primary_keys", []),
            "watermark_column": target_entity_property.get("watermark_column", None),
            "initial_watermark_value": target_entity_property.get("initial_watermark_value", None),
            "seq_col": target_entity_property.get("seq_col", []),
            "partition_col": target_entity_property.get("partition_col", []),
            "except_column_list": target_entity_property.get("except_column_list", None),
        }

        # Remove fields that are still in their default value (None or empty)
        target_entity_property_filtered = {k: v for k, v in target_entity_property_filtered.items() if v not in [None, [], ""]}

        target_entity = TargetEntity(
            data_store=TargetDataStore(
                type=target_data['data_store']['type'],
                properties=TargetDataStoreProperty(
                    **{
                        key: value
                        for key, value in target_data['data_store']['properties'].items()
                    }
                )
            ),
            schema_transform_map=[SchemaTransformMap(**col) for col in target_data['schema_transform_map']],
            property=TargetEntityProperty(**target_entity_property_filtered)
        )

        # Handle table transform
        table_transform_data = data.get('source_to_target_definition', {}).get('table_transform', {})
        table_transform = TableTransform(
            dedup=DedupConfig(
                enabled=table_transform_data.get('dedup', {}).get('enabled', False),
                properties=table_transform_data.get('dedup', {}).get('properties', {})
            ),
            cdc=CdcConfig(
                enabled=table_transform_data.get('cdc', {}).get('enabled', False),
                properties=table_transform_data.get('cdc', {}).get('properties', {})
            ),
            load_strategy=LoadStrategyConfig(
                mode=table_transform_data.get('load_strategy', {}).get('mode', '')
            )
        )

        # Handle rules
        rules_data = data.get('source_to_target_definition', {}).get('rules', {})
        rules = Rules(
            bronze=RulesConfig(
                Error=RuleType(
                    literal=Rule(rule=rules_data['bronze']['Error']['literal']['rule']),
                    derived=Rule(rule=rules_data['bronze']['Error'].get('derived', {}).get('rule', '')) if 'derived' in rules_data['bronze']['Error'] else None
                ),
                Warn=RuleType(
                    literal=Rule(rule=rules_data['bronze']['Warn']['literal']['rule'])
                ) if 'Warn' in rules_data['bronze'] else None
            )
        )

        # Return the full PipelineConfig
        return PipelineConfig(
            source_to_target_definition=SourceToTargetDefinition(
                source_entity=source_entity,
                target_definition=target_entity,
                table_transform=table_transform,
                rules=rules
            )
        )

type_mapping = {
    type(T.IntegerType())    : 'int',
    type(T.DoubleType())     : 'double',
    type(T.LongType())       : 'long',
    type(T.StringType())     : 'string',
    type(T.TimestampType())  : 'timestamp',
    type(T.DateType())       : 'date',
    type(T.BooleanType())    : 'bool',
    type(T.DecimalType())    : 'decimal',
    type(T.ShortType())      : 'short',
    type(T.ByteType())       : 'byte',
    type(T.FloatType())      : 'float',
    type(T.BinaryType())     : 'binary',
    type(T.TimestampNTZType())     : 'timestamp_ntz',
}

def type_to_json(dataType):
    if type(dataType) in type_mapping:
        if isinstance(dataType, T.DecimalType):
            return f"decimal({dataType.precision},{dataType.scale})"
        return type_mapping[type(dataType)]
    
    elif isinstance(dataType, T.StructType):
        return {"struct": generate_source_json_from_schema(dataType)}
    
    elif isinstance(dataType, T.ArrayType):
        return ["array", type_to_json(dataType.elementType)]
    
    elif isinstance(dataType, T.MapType):
        return {
            "map": {
                "keyType": type_to_json(dataType.keyType),
                "valueType": type_to_json(dataType.valueType)
            }
        }
    
    else:
        print(f"Error: {dataType}")
        return "ERROR"

def generate_source_json_from_schema(schema):
    schema_json = []
    for column in schema:
        schema_json.append({
            "column_name": column.name,
            "data_type": type_to_json(column.dataType),
            "nullable": column.nullable
        })
    return schema_json

def generate_destination_json_from_schema(schema) -> List[SchemaTransformMap]:
    schemaTransformMap =[]
    for column in schema:
        # Replace spaces with underscores
        cleaned_column_name = re.sub(r'\s+', '_', column.name)
        # Remove non-alphanumeric characters except for underscores
        cleaned_column_name = re.sub(r'[^a-zA-Z0-9_]', '', cleaned_column_name)
        schemaTransformMap.append(SchemaTransformMap(
            source_column_name=column.name,
            column_name=cleaned_column_name,
            type=type_to_json(column.dataType),
            derived_expression=""
        ))
    return schemaTransformMap

def fetch_table_names(spark: SparkSession, catalog: str, schema: str) -> List[str]:
    """
    This function retrieves metadata for a specified table by running a DESCRIBE TABLE SQL query. It returns a list of Column objects, where each object contains metadata about each column in the table, such as the column name, data type, and nullable status.
    """
    query = f"SHOW TABLES IN {catalog}.{schema}"
    tables_df = spark.sql(query)
    filter_temporary_table = tables_df.filter("isTemporary = 'false'")
    return [row["tableName"] for row in filter_temporary_table.collect()]

def get_file_format(file_path: str) -> str:
    """
    Infers the file format based on the file extension.
    
    Args:
        file_path (str): Path to the file.
    
    Returns:
        str: File format (e.g., 'csv', 'json', etc.)
    """
    if file_path.endswith(".csv"):
        return "csv"
    elif file_path.endswith(".json"):
        return "json"
    elif file_path.endswith(".parquet"):
        return "parquet"
    elif file_path.endswith(".delta"):
        return "delta"
    elif file_path.endswith(".txt") or file_path.endswith(".text"):
        return "text"
    elif file_path.endswith(".avro"):
        return "avro"
    else:
        raise ValueError("Unsupported file format or missing file format argument.")

def read_file_with_dynamic_support(
    spark: SparkSession,
    file_path: str,
    file_format: str = None,
    options: dict = None
):
    """
    Reads a file or files into a Spark DataFrame with dynamic support for various file formats.
    
    Args:
        file_path (str): Path to the file or directory.
        file_format (str, optional): File format to use for reading the file (e.g., 'csv', 'json', etc.). Defaults to None, which infers the format from the file extension.
        options (dict, optional): Options to apply when reading the file (e.g., escape char).
    
    Returns:
        DataFrame: Loaded DataFrame.
    """
    if options is None:
        options = {}

    # Determine if the file_path is a single file or a directory
    if os.path.isfile(file_path):
        # Single file
        if file_format is None:
            file_format = get_file_format(file_path)
        files_to_read = [file_path]
    elif os.path.isdir(file_path):
        # Directory containing multiple files
        files_to_read = [
            os.path.join(file_path, file)
            for file in os.listdir(file_path)
            if not file.startswith(".")  # Exclude hidden files
        ]
        # Infer file format from the first file in the directory
        if len(files_to_read) > 0:
            if file_format is None:
                file_format = get_file_format(files_to_read[0])
        else:
            raise ValueError("Directory is empty or contains no readable files.")
    else:
        raise ValueError("Provided path is neither a valid file nor a directory.")

    # Map default options dynamically
    format_defaults = {
        "csv": lambda: spark.read.format("csv").options(
            header="true", inferSchema="true", escape='"', sep=","
        ),
        "json": lambda: spark.read.format("json").options(multiline="true"),
        "parquet": lambda: spark.read.format("parquet"),
        "delta": lambda: spark.read.format("delta"),
        "text": lambda: spark.read.format("text"),
        "avro": lambda: spark.read.format("avro"),
    }

    # Validate format
    if file_format not in format_defaults:
        raise ValueError(f"Unsupported file format: {file_format}")

    # Get the DataFrame reader with default options
    reader = format_defaults[file_format]()

    # Apply additional options if provided
    reader = reader.options(**options)

    try:
        # Load the file(s) into a DataFrame
        df = reader.load(files_to_read)

        # Extract schema details
        schema = df.schema
        return df, schema
    except AnalysisException as e:
        raise RuntimeError(f"Error reading the file(s): {str(e)}")

def process_input(input_data: Dict[str, Union[str, List[str]]], exclude: List[str] = None) -> List[Dict[str, str]]:
    # Get the exclusion list directly from the input_data dictionary
    exclude = input_data.get("exclude", [])  # Default to empty list if not provided
    
    file_path = input_data.get("file_path")
    file_format = input_data.get("file_format", "")
    case_flag = input_data.get("case_flag", "")
    source_spark_options=input_data.get("source_spark_options", {})
    trigger_type=input_data.get("trigger_type", "availableNow")
    trigger_interval=input_data.get("trigger_interval", "")
    checkpointLocation = input_data.get("checkpointLocation", "")

    result = []

    # Capture file format dynamically if not provided
    def capture_file_format(path):
        return os.path.splitext(path)[-1].lstrip(".")
    
    # Case 1: Single file
    if case_flag == "single_file" and isinstance(file_path, str) and os.path.isfile(file_path):
        file_format = file_format or capture_file_format(file_path)
        if not any(excluded in file_path for excluded in exclude):
            result.append({"file_path": file_path, "file_format": file_format,"source_spark_options":source_spark_options,"trigger_type":trigger_type,"trigger_interval":trigger_interval,"checkpointLocation":checkpointLocation})

    # Case 2: List all files in directory
    elif case_flag == "list_all_files_in_directory" and isinstance(file_path, str) and os.path.isdir(file_path):
        all_files = glob.glob(os.path.join(file_path, f"*.{file_format}" if file_format else "*"))
        for file in all_files:
            if not any(excluded in file for excluded in exclude):
                result.append({"file_path": file, "file_format": capture_file_format(file),"source_spark_options":source_spark_options,"trigger_type":trigger_type,"trigger_interval":trigger_interval,"checkpointLocation":checkpointLocation})

    # Case 3: Get the last file in each directory
    elif case_flag == "get_last_file_in_directory" and isinstance(file_path, str) and os.path.isdir(file_path):
        sub_dirs = [os.path.join(file_path, d) for d in os.listdir(file_path) if os.path.isdir(os.path.join(file_path, d))]
        for sub_dir in sub_dirs:
            if not any(excluded in sub_dir for excluded in exclude):  # Exclude subdirectories
                files = sorted(glob.glob(os.path.join(sub_dir, f"*.{file_format}" if file_format else "*")), key=os.path.getmtime)
                if files:
                    last_file = files[-1]
                    if not any(excluded in last_file for excluded in exclude):  # Exclude files
                        result.append({"file_path": last_file, "file_format": capture_file_format(last_file),"source_spark_options":source_spark_options,"trigger_type":trigger_type,"trigger_interval":trigger_interval,"checkpointLocation":checkpointLocation})

    # case 4: Get the latest file in each directory
    elif case_flag == "get_latest_file_in_directory" and isinstance(file_path, str) and os.path.isdir(file_path):
        all_files = glob.glob(os.path.join(file_path, f"*.{file_format}" if file_format else "*"))
        
        # Filter files based on exclusion criteria
        filtered_files = [file for file in all_files if not any(excluded in file for excluded in exclude)]
        
        if filtered_files:
            # Get the latest file by modification time
            latest_file = max(filtered_files, key=os.path.getmtime)
            
            result.append({
                "file_path": latest_file,
                "file_format": capture_file_format(latest_file),
                "source_spark_options": source_spark_options,
                "trigger_type": trigger_type,
                "trigger_interval": trigger_interval,
                "checkpointLocation":checkpointLocation
            })
    # Case 5: Manually provided file list
    elif case_flag == "manually_provided_file_list" and isinstance(file_path, list):
        for path in file_path:
            if not any(excluded in path for excluded in exclude):
                file_format = file_format or capture_file_format(path)
                result.append({"file_path": path, "file_format": file_format,"source_spark_options":source_spark_options,"trigger_type":trigger_type,"trigger_interval":trigger_interval,"checkpointLocation":checkpointLocation})

    return result


def format_file_path(file_path):
    """
    Format the file path to include a default structure with placeholders for catalog_name and schema_name.

    Args:
        file_path (str): Original file path.

    Returns:
        str: Formatted file path with placeholders for catalog_name and schema_name.
    """
    # Split the file path into parts
    parts = file_path.split("/")
    
    # Ensure there are enough parts
    if len(parts) < 5:
        raise ValueError("File path does not have enough components to split at the 4th '/'.")

    # Insert the placeholders after the 2nd '/'
    formatted_parts = parts[:2] + ["{catalog_name}", "{schema_name}"] + parts[4:]
    
    # Reconstruct the formatted file path
    formatted_path = "/".join(formatted_parts)
    return formatted_path
