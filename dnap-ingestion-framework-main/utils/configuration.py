import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from types import SimpleNamespace

# DataStore class to represent a data store (like a database, file, etc.)
@dataclass
class DataStore:
    type: str  # The type of datastore (e.g., 'catalog', 'file', etc.)
    properties: Optional[Dict[str, str]]  # Dictionary of properties associated with the datastore

    # Method to set the type of the datastore
    def set_type(self, datastore_type: str):
        self.type = datastore_type

    # Method to set the properties of the datastore
    def set_properties(self, properties: Dict[str, str]):
        self.properties = properties

    # Method to set both the type and properties of the datastore
    def set_datastore(self, datastore_type: str, properties: Dict[str, str]):
        self.set_type(datastore_type)
        self.set_properties(properties)


# Column class to represent individual columns in the schema
@dataclass
class Column:
    column_name: str  # Name of the column
    data_type: str  # Data type of the column (e.g., 'string', 'decimal', etc.)
    nullable: bool  # Whether the column can contain null values


# SourceEntityDefinition class to represent the source entity's data store and schema
@dataclass
class SourceEntityDefinition:
    data_store: DataStore  # DataStore associated with the source entity
    schema: List[Column]  # List of Column objects representing the schema
    property: Optional[Dict[str, Optional[List[str]]]]  # Property containing 'primary_keys' and 'watermark_column'


# SchemaTransformMap class to represent the transformation mapping between source and target
@dataclass
class SchemaTransformMap:
    column_name: str  # Name of the column in the target entity
    source_column_name: str  # Name of the corresponding source column
    data_type: str  # Data type of the target column
    derived_expression: Optional[str]  # Optional derived expression (e.g., trim, transform, etc.)


# TargetEntityDefinition class to represent the target entity's data store and transformation schema
@dataclass
class TargetEntityDefinition:
    data_store: DataStore  # DataStore associated with the target entity
    schema_transform_map: List[SchemaTransformMap]  # List of SchemaTransformMap objects for transformations
    property: Optional[Dict[str, Optional[List[str]]]]  # Added property field

# TransformationConfig class to represent the transformation settings (e.g., deduplication)
@dataclass
class TransformationConfig:
    enabled: bool  # Whether the transformation is enabled
    properties: Dict[str, Optional[Dict[str, str]]]  # Additional properties related to the transformation


# TableTransformation class to represent transformations applied to the table (e.g., deduplication)
@dataclass
class TableTransformation:
    dedup: Optional[TransformationConfig]  # Configuration for deduplication transformation
    cdc: Optional[TransformationConfig]    # Configuration for CDC transformation
    load_strategy: Optional[Dict[str, str]]  # New field for load strategy


# Main class that defines the mapping between source and target entities, including table transformations
@dataclass
class SourceToTargetDefinition:
    source_entity: SourceEntityDefinition  # Source entity definition
    target_definition: TargetEntityDefinition  # Target entity definition
    table_transform: Optional[TableTransformation] = None  # Allow table_transform as an optional argument
    full_source_entity_name: str = field(default=None, init=False)  # Fully qualified name of the source entity
    full_target_entity_name: str = field(default=None, init=False)  # Fully qualified name of the target entity

    @classmethod
    def from_dict(cls, data: Dict, env: Optional[str] = None) -> 'SourceToTargetDefinition':
        """
        Load the SourceToTargetDefinition from a dictionary, handling both env-mapped and simple catalog_name.
        :param data: The JSON dictionary to load.
        :param env: Optional; the environment ('dev', 'qa', 'prod') to resolve catalog names if applicable.
        """
        try:
            print("Loaded JSON data:", data)  # Debugging output to check the structure

            # Check if 'source_to_target_definition' exists and if it contains 'source_entity'
            if 'source_to_target_definition' not in data:
                raise KeyError("'source_to_target_definition' key is missing from the data.")

            raw_to_bronze = data['source_to_target_definition']

            if 'source_entity' not in raw_to_bronze:
                raise KeyError("'source_entity' key is missing in 'source_to_target_definition'.")

            # Parse the source entity, including data store and schema
            source_entity = SourceEntityDefinition(
                data_store=DataStore(
                    type=raw_to_bronze['source_entity']['data_store']['type'],
                    properties=raw_to_bronze['source_entity']['data_store']['properties']
                ),
                schema=[Column(**col) for col in raw_to_bronze['source_entity']['schema']],
                property=raw_to_bronze['source_entity']['property']  # Store the property directly
            )

            # Check if target_definition exists in the data
            if 'target_definition' not in raw_to_bronze:
                raise KeyError("'target_definition' key is missing in 'source_to_target_definition'.")

            # Parse the target entity and the schema transformation map
            target_definition = TargetEntityDefinition(
                data_store=DataStore(
                    type=raw_to_bronze['target_definition']['data_store']['type'],
                    properties=raw_to_bronze['target_definition']['data_store']['properties']
                ),
                schema_transform_map=[
                    SchemaTransformMap(
                        column_name=col_map['column_name'],
                        source_column_name=col_map['source_column_name'],
                        data_type=col_map['type'],
                        derived_expression=col_map.get('derived_expression', None)
                    )
                    for col_map in raw_to_bronze['target_definition']['schema_transform_map']
                ],
                property=raw_to_bronze['target_definition']['property']
            )

            # Process table_transform if available
            table_transform = None
            if 'table_transform' in raw_to_bronze and raw_to_bronze.get('table_transform'):
                table_transform_data = raw_to_bronze['table_transform']

            # Handle deduplication
            dedup_config = None
            if 'dedup' in table_transform_data:
                dedup_config = TransformationConfig(
                    enabled=table_transform_data['dedup']['enabled'],
                    properties=table_transform_data['dedup']['properties']
                )

            # Handle CDC
            cdc_config = None
            if 'cdc' in table_transform_data:
                cdc_config = TransformationConfig(
                    enabled=table_transform_data['cdc']['enabled'],
                    properties=table_transform_data['cdc']['properties']
                )

            # Handle load_strategy
            load_strategy = None
            if 'load_strategy' in table_transform_data:
                load_strategy = table_transform_data['load_strategy']  # Assuming it's a simple dictionary

            # Create the TableTransformation object
            table_transform = TableTransformation(
                dedup=dedup_config,
                cdc=cdc_config,
                load_strategy=load_strategy
            )

            # Handle catalog_name for both cases
            def resolve_catalog_name(catalog_name, env):
                if isinstance(catalog_name, dict):
                    if env:
                        if env not in catalog_name:
                            raise ValueError(f"Environment '{env}' not found in catalog_name.")
                        return catalog_name[env]
                    else:
                        # Default to the first key in the dictionary if no env is provided
                        return next(iter(catalog_name.values()))
                elif isinstance(catalog_name, str):
                    return catalog_name
                else:
                    raise TypeError("catalog_name must be either a dictionary or a string.")

            # Resolve the full entity names dynamically
            source_properties = source_entity.data_store.properties
            target_properties = target_definition.data_store.properties

            full_source_entity_name = (
                f"{resolve_catalog_name(source_properties['catalog_name'], env)}."
                f"{source_properties['schema_name']}."
                f"{source_properties['table_name']}"
            )

            full_target_entity_name = (
                f"{resolve_catalog_name(target_properties['catalog_name'], env)}."
                f"{target_properties['schema_name']}."
                f"{target_properties['table_name']}"
            )

            # Create the SourceToTargetDefinition object
            instance = SourceToTargetDefinition(
                source_entity=source_entity,
                target_definition=target_definition,
                table_transform=table_transform
            )

            # Assign the full entity names
            instance.full_source_entity_name = full_source_entity_name
            instance.full_target_entity_name = full_target_entity_name

            return instance

        except KeyError as e:
            print(f"KeyError: {e}. Please check your JSON structure.")
            raise
        except ValueError as e:
            print(f"ValueError: {e}")
            raise
        except TypeError as e:
            print(f"TypeError: {e}")
            raise
        except Exception as e:
            print(f"An error occurred while processing the data: {e}")
            raise

    # Method to load the configuration from a JSON file
    @staticmethod
    def load_config_json(file_path: str) -> 'SourceToTargetDefinition':
        """
        Load the configuration object from the provided JSON file
        """
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)  # Parse the JSON file into a dictionary
                return SourceToTargetDefinition.from_dict(data)  # Create the object from the dictionary
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {file_path}: {e}")
            raise
        except FileNotFoundError as e:
            print(f"File not found: {file_path}. Please check the file path.")
            raise
        except Exception as e:
            print(f"An error occurred while loading the JSON: {e}")
            raise

    # Simple validation method (returns True for now)
    @staticmethod
    def validate() -> bool:
        """
        Returns Boolean for validated state of configuration
        """
        return True


# PipelineConfig class to hold multiple SourceToTargetDefinition objects in a dictionary
@dataclass
class PipelineConfig:
    tables: Dict[str, SourceToTargetDefinition]

    # Method to load a configuration from a JSON file
    @staticmethod
    def load_config(file_path: str) -> Dict:
        """Load the configuration from a JSON file."""
        with open(file_path, 'r') as file:
            return json.load(file)