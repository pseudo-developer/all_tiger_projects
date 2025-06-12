# Configuration Class

## Description

This class represents a configuration object for a specific table.

## Attributes

- `table_name` (str): The name of the table.
- `config_file` (str): The path to the configuration file.
- `config` (dict): The loaded configuration data.

## Methods

- `load_config()`: Loads the json data from the config file.
- `check_addl_source(source_type)`: Checks if the table has additional data source enabled.
- `get_config(source_type='live')`: Returns the current table configuration.
- `set_config(new_config: dict, source_type='live')`: Sets the table configuration to a new value.
- `write_config()`: Writes the current configuration to the config file in json.
- `get_data_source(source_type='live')`: Returns the data source configuration.
- `set_data_source(new_data_source: dict, source_type='live')`: Sets the data source configuration to a new value.
- `get_transformation(source_type='live')`: Returns the transformation configuration.
- `set_transformation(new_transformation: dict, source_type='live')`: Sets the transformation configuration to a new value.
- `get_schema(source_type='live')`: Returns the schema configuration.
- `set_schema(new_schema: dict, source_type='live')`: Sets the schema configuration to a new value.
- `get_cur_schema()`: Returns the current schema of the table.
- `set_cur_schema(new_schema: T.StructType)`: Sets the current schema of the table to a new value.
- `get_spark_schema(source_type='live')`: Returns the generated Spark schema.
- `get_primary_keys(source_type='live')`: Returns the list of primary keys for the table.
- `get_rule(quality_level, rule_action)`: Returns the rule configurations for the given quality level and rule action.
- `set_rule(quality_level, rule_action, new_rule: dict)`: Sets the rule configurations for the given quality level and rule action to a new value.
- `get_expectations(quality_level, rule_action)`: Returns the list of expectations for the given quality level and rule action.

## Usage

```python
from redshift.Workflow.utils.configuration import Configuration

# Create a Configuration object
config = Configuration('table_name', 'config_file.json')

# Load the configuration
config.load_config()

# Get the current table configuration
current_config = config.get_config()

# Set a new table configuration
new_config = {'key': 'value'}
config.set_config(new_config)

# Write the configuration to the config file
config.write_config()

# Get the data source configuration
data_source = config.get_data_source()

# Set a new data source configuration
new_data_source = {'key': 'value'}
config.set_data_source(new_data_source)

# Get the transformation configuration
transformation = config.get_transformation()

# Set a new transformation configuration
new_transformation = {'key': 'value'}
config.set_transformation(new_transformation)

# Get the schema configuration
schema = config.get_schema()

# Set a new schema configuration
new_schema = {'key': 'value'}
config.set_schema(new_schema)

# Get the current schema of the table
current_schema = config.get_cur_schema()

# Set the current schema of the table
new_schema = T.StructType()
config.set_cur_schema(new_schema)

# Get the generated Spark schema
spark_schema = config.get_spark_schema()

# Get the list of primary keys
primary_keys = config.get_primary_keys()

# Get the rule configurations
rule_config = config.get_rule('quality_level', 'rule_action')

# Set a new rule configuration
new_rule = {'key': 'value'}
config.set_rule('quality_level', 'rule_action', new_rule)

# Get the list of expectations
expectations = config.get_expectations('quality_level', 'rule_action')
```
