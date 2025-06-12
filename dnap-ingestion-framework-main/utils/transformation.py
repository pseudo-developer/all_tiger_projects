import pyspark.sql.functions as F
import pyspark.sql.types as T
import re
# from advutils.helper import get_type
# from utils.helper import get_type


def validate_transformation(tbl_config, transformation, source_type='live') -> bool: 
    return (
        tbl_config.get_transformation(source_type) is not None 
        and transformation in tbl_config.get_transformation(source_type)
        and tbl_config.get_transformation(source_type)[transformation]['enabled']
    )


def calculate_column_selections(df, tbl_config, source_type='live'): 
    if not validate_transformation(tbl_config, 'calculate_column_selections', source_type):
        return df
        
    src_cols          = df.columns
    tgt_cols          = tbl_config.get_schema(source_type)
    column_selections = []

    for col_name in src_cols: 
        # Ignore all columns not specified in schema and column that are marked to drop
        if col_name not in tgt_cols or tgt_cols[col_name].get('drop', False): 
            continue
        else:
            # column_selections.append(col(col_name).cast(get_type(tgt_cols[col_name]['type'])).alias(col_name))
            column_selections.append(F.col(col_name))

    transformed_df = df.select(column_selections)

    return transformed_df


def clean_col_name(df, tbl_config, source_type='live'): 
    if not validate_transformation(tbl_config, 'clean_col_name', source_type):
        return df

    transformed_df = df.toDF(*[re.sub(r'[\)|\(|\s| |,]', '', col_name) for col_name in df.columns])
    
    return transformed_df


def rename_columns(df, tbl_config, col_mapping=None, source_type='live'): 
    # using col_mapping to rename columns if provided
    if col_mapping is not None and isinstance(col_mapping, dict): 
        transformed_df = df.withColumnsRenamed(col_mapping)

        return transformed_df

    if not validate_transformation(tbl_config, 'rename_columns', source_type):
        return df
    
    transformed_df = df.withColumnsRenamed(tbl_config.get_transformation(source_type)['rename_columns']['mapping'])
    
    return transformed_df


def dedup(df, key=None, exclude_columns=None):
    """
    Deduplicate records in a DataFrame.
    
    :param df: Input DataFrame
    :param key: List of columns to consider for deduplication (optional)
    :param exclude_columns: List of columns to exclude from deduplication (optional)
    :return: Deduplicated DataFrame
    """
    if key and exclude_columns:
        print("Both key and exclude_columns are specified. Only key will be considered.")
        # Deduplicate using the key but ensure exclude_columns are not considered
        columns_to_consider = [col for col in key if col not in exclude_columns]
        return df.dropDuplicates(columns_to_consider)

    if key:
        return df.dropDuplicates(key)

    if exclude_columns:
        columns_to_consider = [col for col in df.columns if col not in exclude_columns]
        return df.dropDuplicates(columns_to_consider)
    else:
        return df.dropDuplicates()
    

# def type_cast(df, tbl_config, type_mapping=None, source_type='live'): 
#     # using type_mapping to cast columns if provided
#     if type_mapping is not None and isinstance(type_mapping, dict): 
#         transformed_df = df.withColumns({
#             col_name: col(col_name).cast(get_type(col_type)) for col_name, col_type in type_mapping.items()
#         })

#         return transformed_df
    
#     if not validate_transformation(tbl_config, 'type_cast', source_type):
#         return df
    
#     type_mapping = tbl_config.get_transformation(source_type)['type_cast']['mapping']
#     transformed_df = df.withColumns({
#         col_name: F.col(col_name).cast(get_type(col_type)) for col_name, col_type in type_mapping.items()
#     })

#     return transformed_df

def add_column_expr(df, tbl_config, source_type='live'):
    # checks that the column expressions config exists & is enabled, otherwise returns the original df
    if not validate_transformation(tbl_config, 'add_column_expressions', source_type):
        return df

    #create columns from the given expressions if provided
    add_col_config = tbl_config.get_transformation(source_type)['add_column_expressions']['mapping']
    transformed_df = df.withColumns({
        col_name: F.lit(col_expr) for col_name, col_expr in add_col_config.items()
    })

    return transformed_df

def column_value_expr(df, tbl_config, source_type='live'):
    # apply an expression to a column

    column_value_expr = tbl_config.get_transformation(source_type)['column_value_expressions']

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