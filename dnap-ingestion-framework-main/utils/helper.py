import pyspark
import json
import re
import pyspark.sql.types as T
import pyspark.sql.functions as F
import configuration
from delta.tables import DeltaTable
from pyspark.sql import SparkSession, DataFrame, Column
from os import listdir
from os.path import isfile, join
from datetime import datetime
from pyspark.sql.utils import AnalysisException

# Initialize Spark session
spark = SparkSession.builder \
    .getOrCreate()

def convert_null(col_obj: Column) -> Column:
    """
    Converts null values in a column to the string 'NULL'.

    Args:
        col_obj (pyspark.sql.Column): The column object to be converted.

    Returns:
        pyspark.sql.Column: The converted column object.
    """
    return F.when(col_obj.eqNullSafe(None), F.lit('NULL')).otherwise(col_obj)

def column_cast(field: T.StructField):
    """
    Casts the column of a DataFrame based on its data type.

    Args:
        field (pyspark.sql.types.StructField): The field representing the column.

    Returns:
        pyspark.sql.Column: The casted column.

    Raises:
        None

    Examples:
        >>> field = T.StructField("age", T.IntegerType(), True)
        >>> column_cast(field)
        Column<b'convert_null(cast(age as string)) AS age'>
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

def add_etl_cols(df, batch_id):
      """
      Add additional ETL columns to Dataframe

      Args:
            df: Dataframe to add additonal columns to
            pac_batch_id: id of run consisting of job run id and task run id
            pac_load_timestamp: timestamp of run
      Returns:
            Dataframe with additional columns
      
      Usage:
            df = df.tansform(add_etl_cols,  pac_batch_id)
            df = add_etl_cols(df,  batch_id)
      """
      return (
        df
        .withColumn("pac_batch_id", F.lit(batch_id))
        .withColumn("pac_load_timestamp", F.current_timestamp())
      )

# Add hash keys for primary key and non-primary key columns
def add_hash_key(df: DataFrame, pk_columns: list) -> DataFrame:
    all_columns = df.schema.fields  # Get StructField objects
    non_pk_columns = [field for field in all_columns if field.name not in pk_columns]
    
    # Apply hash key for primary key columns
    if pk_columns:
        df = df.withColumn(
            'pac_hash_key',
            F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns if field.name in pk_columns]))
        )
    else:
        # Apply hash key for non-primary key columns
        df = df.withColumn(
            'pac_hash_key',
            F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns]))
        )
    
    df = df.withColumn(
        'pac_hash_key_non_pk',
        F.md5(F.concat_ws('|', *[column_cast(field) for field in all_columns]))
    )
    
    return df


def build_source_query(source_table, watermark_column, watermark_value, source_schema, schema_transform_map):
    """Build a dynamic source query based on extraction type."""
    
    # Extract source column names and their mapped aliases
    column_alias_map = {
        item.source_column_name: item.column_name
        for item in schema_transform_map
        if item.source_column_name  # Exclude empty source_column_name
    }

    # Generate the SELECT statement with aliasing
    column_name_str = ', '.join([
        f"`{src}` AS `{column_alias_map[src]}`" if src in column_alias_map else f"`{src}`"
        for src in [col.column_name for col in source_schema]  # Use dot notation here
    ])

    if watermark_column:
        # Resolve watermark_column using schema_transform_map
        for item in schema_transform_map:           
            # Normalize and compare
            if item.column_name.strip().lower() == watermark_column.strip().lower():
                # Update watermark_column if match is found
                watermark_column = item.source_column_name
                break
        else:
            # If no match is found after checking all items
            raise ValueError(f"No match found for column: {watermark_column}")  
        
        if watermark_value is None:
            return f"""SELECT {column_name_str} FROM {source_table}"""
        else:
            return f"""
            SELECT {column_name_str} FROM {source_table}
            WHERE `{watermark_column}` > CAST('{watermark_value}' AS TIMESTAMP)
            """
    else:
        print(source_table)
        return f"SELECT {column_name_str} FROM {source_table}"

def get_df_from_source(source_datasource_type, connection=None, query=None):
    print(f"source_datasource_type: {source_datasource_type}")
    """
    Returns dataframe from data based on datasource_type and connection

    Args:
        source_datasource_type: CATALOG, MSSQGL
        connection: dictionary containing connection information - (MSSQL: Server, User Id, Password, Database
        query: optional query to execute rather than SQL Server table

    Returns:
        Dataframe containing query or table results
    """
    if query:
        print('query', query)
        df = spark.sql(query)
    return df

def union_by_name_dfs(*dataframes: DataFrame) -> DataFrame:
    # Start with None
    result_df = None

    for df in dataframes:
        if not df.isEmpty():
            result_df = df if result_df is None else result_df.unionByName(df)

    return result_df

def build_cdc(source_Df: DataFrame, target_Df: DataFrame,exclude_cols: list,pk_columns: list, watermark_column: str) -> DataFrame:
    # Assuming you have these DataFrames defined earlier
    # source_df = DataFrame with new records
    # target_df = DataFrame with current records
    if watermark_column is None:
        # 1. DELETE operation
        # Step 1: Perform a left anti join to find records in target_Df not present in source_Df
        missing_from_source = (
            target_Df
            .join(
                source_Df.select('pac_hash_key'),  # Comparing by 'pac_hash_key'
                'pac_hash_key',
                'left_anti'  # Get records in target_Df that are not in source_Df
            )
        )

        # Step 2: Select only the columns from source_Df and add the 'pac_operation' column
        # We assume source_Df and target_Df share the 'pac_hash_key' column and other needed columns
        del_Df = (
            missing_from_source
            .select(source_Df.columns)  # Select only the columns from source_Df
            .withColumn('pac_operation', F.lit('DELETE'))  # Add the 'pac_operation' column
        )

    # 2. INSERT operation
    ins_Df = (
        source_Df
        .join(
            target_Df,
            'pac_hash_key',
            'leftanti'
        )
        .withColumn('pac_operation', F.lit('INSERT'))
    )

    if pk_columns:
        # 3. UPDATE operation
        # Drop the 'pac_operation' column before joining
        target_selected = target_Df.drop(*exclude_cols)
        source_selected = source_Df.drop(*exclude_cols)

        # Perform the inner join to find matching records
        joined_Df = target_selected.alias("t").join(source_selected.alias("s"), 'pac_hash_key', 'inner').filter(
            (F.col("t.pac_hash_key_non_pk") != F.col("s.pac_hash_key_non_pk"))
            ).select("s.*")
        # Identify updated records by comparing columns
        update_Df = (
            joined_Df
            .join(ins_Df, 'pac_hash_key', 'leftanti')  # Exclude records in ins_Df
            .select(joined_Df["*"], F.lit('UPDATE').alias('pac_operation'))
        )

        if watermark_column is None:
            cdc_Df =union_by_name_dfs(del_Df, ins_Df, update_Df)
        else:
            cdc_Df =union_by_name_dfs(ins_Df, update_Df)
    else:
        if watermark_column is None:
            cdc_Df =union_by_name_dfs(del_Df, ins_Df)
        else:
            cdc_Df = ins_Df
    return cdc_Df

def df_is_empty(df):
    if df.count() == 0:
        return True
    return False


def delta_table_exists(spark: SparkSession, qualified_table_name: str) -> bool:
    """
    Checks if a Delta table exists in the specified catalog and schema.

    Parameters:
    spark (SparkSession): The Spark session to use for executing the query.
    qualified_table_name (str): The fully qualified table name in the format 'catalog.schema.table_name'.

    Returns:
    bool: True if the Delta table exists, False otherwise.

    Command:
    1. Splits the qualified table name into catalog, schema, and table name.
    2. Constructs a SQL query to check if a table with the specified name exists in the given catalog and schema.
    3. Executes the query using Spark SQL to retrieve the result.
    4. Returns True if the result contains any rows (indicating the table exists), otherwise returns False.
    """

    # Split the qualified table name by '.'
    catalog, schema, table_name = qualified_table_name.split('.')

    # Construct the query to check for table existence
    query = f"SHOW TABLES IN {catalog}.{schema} LIKE '{table_name}'"

    # Execute the query and collect the result
    result = spark.sql(query).count()

    # Return True if any rows are found, indicating the table exists
    return result > 0

    
def get_config_files(configuration_path):
    try:
        config_file_path_list = [
            configuration_path + "/" + f
            for f in listdir(configuration_path)
            if isfile(join(configuration_path, f)) and f.endswith(".json")
        ]
        
        return config_file_path_list
    except Exception as e:
        print(e)

def load_pipeline_configs(config_files, env=None) -> configuration.PipelineConfig:
    """
    Load and parse the pipeline configuration from provided config files.
    
    :param config_files: The configuration files to load.
    :param env: Optional; the environment ('dev', 'qa', 'prod') to resolve catalog names if applicable.
    :return: A PipelineConfig object.
    """
    try:
        # Load the raw configuration data
        config_data = configuration.PipelineConfig.load_config(config_files)

        # Create the pipeline configuration, passing the optional `env`
        pipeline_config = configuration.SourceToTargetDefinition.from_dict(config_data, env=env)
        
        print(f"pipeline_config loaded successfully for environment '{env}': {pipeline_config}")
        return pipeline_config

    except KeyError as e:
        print(f"KeyError: {e}")
        # Optionally, print out the problematic part of data
        print(f"Problematic config data: {config_data}")
        raise  # Re-raise the error for upstream handling
    except Exception as e:
        print(f"An error occurred while processing {config_files} for environment '{env}': {e}")
        raise  # Re-raise the error for upstream handling


def get_watermark_value(
    bronze_full_target_entity_name: str, 
    watermark_column: str = None, 
    initial_watermark_value=None
) -> str:
    """
    Initialize the watermark value based on the configuration file or initial value.

    Parameters:
        bronze_full_target_entity_name (str): Full target entity name of the bronze table.
        watermark_column (str, optional): Column used as the watermark.
        initial_watermark_value (any, optional): Initial value to use if no existing watermark is found.

    Returns:
        str: The initialized watermark value, or None if no valid value is found.
    """
    if watermark_column is not None:
        # Check if the delta table exists and fetch the maximum watermark value
        if delta_table_exists(spark, bronze_full_target_entity_name):
            watermark_value = spark.sql(
                f"SELECT MAX({watermark_column}) FROM {bronze_full_target_entity_name}"
            ).collect()[0][0]
        else:
            watermark_value = None

        # Use the initial watermark value if no valid value is found
        if watermark_value is None and initial_watermark_value is not None:
            watermark_value = initial_watermark_value
    else:
        # Set watermark value to None if no column is provided
        watermark_value = None

    return watermark_value

# Function to get the PySpark data type
def get_spark_type(type_str: str):
    type_str = type_str.strip().lower()

    if type_str in {"string", "varchar", "char", "text", "nvarchar"} or type_str.startswith("varchar(") or  type_str.startswith("char("):
        return T.StringType()
    elif type_str in {"int", "integer"}:
        return T.IntegerType()
    elif type_str in {"bigint", "long"}:
        return T.LongType()
    elif type_str in {"short", "smallint"}:
        return T.ShortType()
    elif type_str in {"byte", "tinyint"}:
        return T.ByteType()
    elif type_str in {"float", "float32"}:
        return T.FloatType()
    elif type_str in {"double", "float64"}:
        return T.DoubleType()
    elif type_str.startswith("decimal"):
        # Look for "decimal(precision, scale)"
        match = re.match(r"decimal\((\d+),\s*(\d+)\)", type_str)
        if match:
            precision = int(match.group(1))
            scale = int(match.group(2))
            return T.DecimalType(precision, scale)
        else:
            # Default decimal type (decimal(10, 0))
            return T.DecimalType(10, 0)
    elif type_str in {"boolean", "bool"}:
        return T.BooleanType()
    elif type_str in {"binary", "blob"}:
        return T.BinaryType()
    elif type_str in {"date"}:
        return T.DateType()
    elif type_str in {"timestamp", "timestamp_ltz"}:
        return T.TimestampType()
    elif type_str in {"timestamp_ntz"}:
        return T.TimestampNTZType()
    elif type_str in {"null", "void"}:
        return T.NullType()
    elif type_str.startswith("yearmonthinterval"):
        # Example: yearmonthinterval(year, month)
        match = re.match(r"yearmonthinterval\((\w+),\s*(\w+)\)", type_str)
        if match:
            start_field, end_field = match.groups()
            start_field = 1 if start_field == "year" else 0
            end_field = 0 if end_field == "month" else 1
            return T.YearMonthIntervalType(start_field, end_field)
    elif type_str.startswith("daytimeinterval"):
        # Example: daytimeinterval(day, hour)
        match = re.match(r"daytimeinterval\((\w+),\s*(\w+)\)", type_str)
        if match:
            start_field, end_field = match.groups()
            start_field = {"day": 0, "hour": 1, "minute": 2, "second": 3}[start_field]
            end_field = {"day": 0, "hour": 1, "minute": 2, "second": 3}[end_field]
            return T.DayTimeIntervalType(start_field, end_field)
    elif type_str.startswith("array"):
        # Example: array<string>
        inner_type = type_str[type_str.index('<')+1:type_str.index('>')].strip()
        return T.ArrayType(get_spark_type(inner_type))
    elif type_str.startswith("map"):
        # Example: map<string, int>
        key_val_types = type_str[type_str.index('<')+1:type_str.index('>')].split(',')
        key_type = get_spark_type(key_val_types[0].strip())
        value_type = get_spark_type(key_val_types[1].strip())
        return T.MapType(key_type, value_type)
    elif type_str.startswith("struct"):
        # Example: struct<field1: int, field2: string>
        fields = type_str[type_str.index('<')+1:type_str.index('>')].split(',')
        struct_fields = []
        for field in fields:
            field_name, field_type = field.split(':')
            struct_fields.append(T.StructField(field_name.strip(), get_spark_type(field_type.strip())))
        return T.StructType(struct_fields)
    else:
        raise ValueError(f"Unsupported type: {type_str}")


def add_dynamic_columns_with_type_check(df, schema_transform_map, apply_only_derived=False):
    """
    Function to add dynamic columns with type checks and derived expressions.
    If `apply_only_derived` is True, only derived expressions are applied.
    """
    for transform in schema_transform_map:
        column_name = transform.column_name
        source_column_name = transform.source_column_name
        derived_expression = transform.derived_expression
        column_type = transform.data_type

        if len(derived_expression) > 0:
            df = df.withColumn(column_name, F.expr(derived_expression))
            print(f"Generating column {column_name} from expr: {derived_expression}")
            continue

        # If only derived expressions should be applied
        if apply_only_derived:
            if derived_expression:
                try:
                    df = df.withColumn(column_name, F.expr(derived_expression))
                except Exception as e:
                    print(f"Error applying derived expression for column {column_name}: {e}")
            continue  # Skip renaming and casting for this mode

        #Checking if renaming is necessary to prevent errors
        if source_column_name and source_column_name in df.columns and source_column_name != column_name:
            df = df.withColumnRenamed(source_column_name, column_name)

        # Applying derived expression if any, with error handling
        if derived_expression:
            try:
                derived_col = eval(derived_expression)
                df = df.withColumn(column_name, derived_col)
            except Exception as e:
                print(f"Error applying derived expression for column {column_name}: {e}")

        # Convert the column type based on the schema only if column exists
        if column_type and column_name in df.columns:
            spark_type = get_spark_type(column_type)
            df = df.withColumn(column_name, df[column_name].cast(spark_type))

    # Select only the columns specified in schema_transform_map
    if not apply_only_derived:
        selected_columns = [transform.column_name for transform in schema_transform_map]
        df = df.select(*selected_columns)

    return df

def file_loader(
    input_path: str,
    options: dict,
    schema: T.StructType = None
):
    """
    Reads streaming data from a given path using dynamic options.

    Args:
        input_path (str): The path to the input data directory.
        options (dict): Dictionary containing dynamic options for the reader.
        schema (StructType, optional): Schema for the data. If not provided, schema inference will be used.

    Returns:
        DataFrame: The resulting DataFrame from the input data.
    """
    # Initialize the reader
    reader = spark.readStream.format("cloudFiles")
    
    # Apply dynamic options
    for key, value in options.items():
        reader = reader.option(key, value)
    
    # Apply schema if provided
    if schema:
        reader = reader.schema(schema)
    
    # Load data from the specified path
    df = reader.load(input_path)
    return df

def convert_schema_to_structtype(df):
    """
    Converts a DataFrame's schema to a manually defined StructType format.
    
    Args:
        df (DataFrame): The DataFrame from which to extract the schema.
        
    Returns:
        StructType: A manually defined StructType that matches the DataFrame's schema.
    """
    # Get the schema from the DataFrame
    df_schema = df.schema
    
    # Convert df.schema to the manual StructType format
    manual_schema = T.StructType([
        T.StructField(field.name, field.dataType, field.nullable) 
        for field in df_schema.fields
    ])
    
    return manual_schema

def write_delta_stream(
    data_frame,
    table_name,
    output_mode="append",
    trigger_type="availableNow",  # Default to availableNow
    trigger_interval=None,
    target_spark_options=None,
):
    """
    Write a DataFrame to a Delta table as a streaming query.

    Parameters:
        data_frame (DataFrame): The input DataFrame to be written.
        table_name (str): The target Delta table name (fully qualified).
        output_mode (str, optional): The output mode ('append', 'complete', 'update'). Default is 'append'.
        trigger_type (str, optional): Type of trigger ('availableNow', 'once', or 'processingTime'). Default is 'availableNow'.
        trigger_interval (str, optional): Interval for triggering (e.g., '5 seconds') if trigger_type is 'processingTime'.
        target_spark_options (dict, optional): Any additional options for the writeStream.

    Returns:
        None: The function waits for the streaming process to complete using query.awaitTermination().
    """
    # Set up the writeStream configuration
    stream_writer = (
        data_frame.writeStream
        .format("delta")  # Specify Delta format
        .outputMode(output_mode)  # Set output mode
    )

    # Apply trigger configuration
    if trigger_type == "availableNow":
        stream_writer = stream_writer.trigger(availableNow=True)
    elif trigger_type == "once":
        stream_writer = stream_writer.trigger(once=True)
    elif trigger_type == "processingTime" and trigger_interval:
        stream_writer = stream_writer.trigger(processingTime=trigger_interval)
    else:
        raise ValueError(
            "Invalid trigger_type. Use 'availableNow', 'once', or 'processingTime' with a valid interval."
        )

    # Add additional options if provided
    if target_spark_options:
        for key, value in target_spark_options.items():
            stream_writer = stream_writer.option(key, value)

    # Write to the target Delta table
    query = stream_writer.toTable(table_name)

    # Await termination to ensure the process completes
    query.awaitTermination()

def set_dynamic_file_location(properties: dict, file_location: str, environment: str):
    """
    Dynamically sets the file location for the datastore based on placeholders.

    Parameters:
    - properties: A dictionary containing key-value pairs for placeholders.
    - file_location: The file location string with placeholders (e.g., '/Volumes/{catalog_name}/{schema_name}/input/')
    """
    # Handle catalog_name based on environment
    if "catalog_name" in properties and isinstance(properties["catalog_name"], dict):
        catalog_name = properties["catalog_name"].get(environment)
        if catalog_name:
            properties["catalog_name"] = catalog_name
        else:
            raise ValueError(f"Environment '{environment}' not found in 'catalog_name' properties.")

    # Replace placeholders in file_location
    for key, value in properties.items():
        if not isinstance(value, dict):  # Skip nested dictionaries like catalog_name
            placeholder = f"{{{key}}}"
            if placeholder in file_location:
                file_location = file_location.replace(placeholder, str(value))
    
    return file_location

# Function to create schema from source_schema
def create_schema_from_transform_map(source_schema):
    schema_fields = []
    
    # Iterate over the source_schema and map fields to PySpark data types
    for field in source_schema:
        column_name = field.column_name
        field_type = field.data_type.lower()
        
        # Use get_spark_type to dynamically get the PySpark data type
        data_type = get_spark_type(field_type)
        
        # Add the column definition to the schema list
        schema_fields.append(T.StructField(column_name, data_type, field.nullable))
    
    # Return the StructType schema
    return T.StructType(schema_fields)

# Helper function to check if a column exists in the source table
def column_exists(catalog, schema, table_name, column_name):
    try:
        # Retrieve the schema of the table
        columns_list = spark.read.table(f"{catalog}.{schema}.{table_name}").columns
        return column_name in columns_list
    except AnalysisException:
        raise ValueError(f"Table {catalog}.{schema}.{table_name} does not exist")
def alter_table_cluster_by(table_name: str, partition_col_list: list):
    """
    Generates and executes an ALTER TABLE SQL statement to CLUSTER BY columns.
    
    Parameters:
    table_name (str): Full name of the table to alter.
    partition_col_list (list): List of columns to use for CLUSTER BY.
    
    Raises:
    ValueError: If the length of partition_col_list is greater than 4.
    Exception: If the SQL execution fails.
    """
    # Check if the length of partition_col_list is valid
    if len(partition_col_list) > 4:
        raise ValueError("The number of partition columns cannot exceed 4.")
    
    # Join the partition column list into a comma-separated string
    cluster_columns = ", ".join(partition_col_list)
    
    # Construct the SQL statement
    sql_statement = f"""
    ALTER TABLE {table_name} 
    CLUSTER BY ({cluster_columns});
    """
    
    # Execute the SQL statement in Databricks or Spark
    try:
        spark.sql(sql_statement)
        print("Table successfully altered with cluster columns.")
    except Exception as e:
        raise Exception(f"Failed to execute SQL statement: {e}")

def check_columns_statistics(table_name, column_list):
    """
    The `check_columns_statistics` function validates and manages the column data types of a specified table.
    It checks for excluded data types (boolean, binary, or map) and ensures all columns in the provided `column_list` 
    exist in the table. If not, it updates the table's properties by adding the necessary columns to the 
    `delta.dataSkippingStatsColumns` property.

    Parameters:
    - table_name (str): The full name of the table in the format `<catalog>.<schema>.<table>`.
    - column_list (list of str): A list of column names to ensure their presence in the table properties.
    """
    # Get the DESCRIBE EXTENDED result for the table
    describe_extended = spark.sql(f"DESCRIBE EXTENDED {table_name}")
    # Extract columns with boolean or binary data types
    boolean_binary_columns = (
        describe_extended
        .filter(F.col("data_type").rlike(r"(?i)\b(boolean|binary|map)\b"))
        .collect()
    )
    # Filter the result to get the 'Column Names' section
    describe_extended_filter = describe_extended.filter(F.col("col_name") == "Column Names").collect()
    # Extract the list of columns from the filtered DataFrame
    boolean_binary_in_table = []
    column_names_in_table = []
    for row in boolean_binary_columns:
        # Split data_type by commas to handle each column separately
        columns = row['col_name'].split(',')
        boolean_binary_in_table.extend(columns)
    boolean_binary_in_table = [col.strip() for col in boolean_binary_in_table]
    for row in describe_extended_filter:
        # Split data_type by commas to handle each column separately
        columns = row['data_type'].split(',')
        column_names_in_table.extend(columns)
    # Clean up and strip extra spaces if any
    column_names_in_table = [col.strip() for col in column_names_in_table]
    bin_bool_remove_columns = [col for col in column_names_in_table if col not in boolean_binary_in_table]
    # Check if all columns in the column_list are present in the table's columns
    missing_columns = [col for col in column_list if col not in column_names_in_table]
    if missing_columns:
        # Concatenate missing_columns with column_names_in_table properly
        columns_to_stats = ', '.join(missing_columns + bin_bool_remove_columns)
        return spark.sql(f"ALTER TABLE {table_name} set tblproperties (delta.dataSkippingStatsColumns = '{columns_to_stats}');")
    else:
        return f"All columns are present in the table '{table_name}'."

def get_initial_columns_with_check(source_catalog, source_schema, source_table_name, check_columns, exclude_columns=None, return_as_list=True):
    """
    Returns the first 32 column names from the table, excluding columns of types boolean, binary, or map.
    Ensures that all columns in `check_columns` are included in the result and excludes specified columns.

    Parameters:
    - source_catalog: The catalog name of the source table.
    - source_schema: The schema name of the source table.
    - source_table_name: The table name.
    - check_columns: List of column names to ensure their presence.
    - exclude_columns: List of column names to exclude from the schema (default is None).
    - return_as_list: Boolean, if True returns a list, otherwise a comma-separated string.

    Returns:
    - List of column names or a comma-separated string.
    """
    # Default to an empty list if exclude_columns is not provided
    if exclude_columns is None:
        exclude_columns = []

    # Read the schema of the table
    schema = spark.readStream.table(f"{source_catalog}.{source_schema}.{source_table_name}").schema

    # Filter out excluded columns
    filtered_columns = [field for field in schema.fields if field.name not in exclude_columns]

    # Get the first 32 valid columns
    initial_columns = filtered_columns[:32]

    # Filter out columns of type boolean, binary, or map
    valid_columns = [field.name for field in initial_columns if not isinstance(field.dataType, (T.BooleanType, T.BinaryType, T.MapType))]

    # Add any missing columns from `check_columns` to the list
    for col in check_columns:
        if col not in valid_columns:
            valid_columns.append(col)

    # Return result in the desired format
    if return_as_list:
        return valid_columns
    else:
        return ",".join(valid_columns)
    
# Function to check if a volume exists in the specified catalog and schema
def volume_exists(catalog, schema, volume):
    """
    Check if a specific volume exists within the given catalog and schema.

    Parameters:
    catalog (str): The name of the catalog.
    schema (str): The name of the schema.
    volume (str): The name of the volume to check.

    Returns:
    bool: True if the volume exists, False otherwise.
    """
    # Construct a query to show all volumes in the specified catalog and schema
    query = f"SHOW VOLUMES FROM {catalog}.{schema}"
    # Execute the query using Spark SQL and store the result in a DataFrame
    volumes_df = spark.sql(query)
    # Check if the specified volume name is in the list of volumes returned by the query
    return volume in [row.volume_name for row in volumes_df.collect()]

# Write the transformed CDC DataFrame to the Delta table in append mode without any partitioning 
def write_data_to_delta(cdc_Df_transformed, full_target_entity_name, partition_col_list=None, partition_cluster_flag=None):
    # Write data with or without partitioning
    if partition_col_list:
        # Ensure partition columns exist in DataFrame
        for col in partition_col_list:
            if col not in cdc_Df_transformed.columns:
                raise ValueError(f"Partition column '{col}' not found in DataFrame.")

        if partition_cluster_flag == 'partition':
            # Write the transformed CDC DataFrame to the Delta table in append mode with the specified partitioning.
            cdc_Df_transformed.write.mode("append").partitionBy(*partition_col_list).format("delta").saveAsTable(full_target_entity_name)
            
        elif partition_cluster_flag == 'liquid':
            # Write the transformed CDC DataFrame to the Delta table in append mode with the specified clustering.
            cdc_Df_transformed.write.mode("append").format("delta").saveAsTable(full_target_entity_name)
            check_statistics = check_columns_statistics(full_target_entity_name, partition_col_list)
            add_clustering = alter_table_cluster_by(full_target_entity_name, partition_col_list)

    else:
        # Write the transformed CDC DataFrame to the Delta table in append mode without any partitioning
        cdc_Df_transformed.write.mode("append").format("delta").saveAsTable(full_target_entity_name)