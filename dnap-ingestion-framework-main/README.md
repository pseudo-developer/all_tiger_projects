# Data & Analytics Ingestion Framework
## How to use the framework
### Prerequisites
* Install databricks-cli locally
* Setup product repository

### Step 1: Setup Asset Bundle
1. Run databricks initialization
2. Create databricks.yml, you may use the example provided in this repository, changing any relevant values like names
3. Start with copies of the examples/workflows & examples/pipelines, adjusting names until you know something else is required
### Step 2: Generate table JSON configuration for source to raw (+ cdc)
1. Run tools/json_config_generator.py, plugging in your source catalog & schema to generate the raw JSON files
2. Place the files back in your repo (unless otherwise specified in your product's design)
### Step 3: Manual Deploy to Dev
1. login to dev: `databricks auth login -p dev`
2. deploy: `databricks bundle deploy -t dev -p dev`
### Step 4: Setup CI/CD
### Step 5: Automated deploy to dev
1. Run the pipeline but against your development feature branch & pass any needed env parameters
### Step 6: Submit PR & auto deploy to QA
1. Commit your changes to your branch & create a pull request
2. This triggers a QA deployment for testing & validation

## CDC
Must be specified by the inclusion of either PrimaryKeys or Watermark. Will default to off if neither is provided. 

## Table Configuration

An auto-generation tool is provided that can read defined datasources & build the configuration files automatically. Manual review should be expected, to adjust to fit project needs, but the aim of the tool is to save time with handling boiler plate configuration.
[tools/Generate Configuration Files from Existing Tables.py](./tools/Generate%20Configuration%20Files%20from%20Existing%20Tables.py)

Features:
- JSON (.json) or YAML (.yml/.yaml) file types supported
- Each configuration file specified can be one or many tables, grouped as you see fit.

Minimal Specification
NOTE: By using the minimal specification, defaults on CDC & schemas will be used. Double check those settings & override as needed
```yaml
<source_to_target_definition_1>: # Required
  source_entity: # Required
    data_store: # Required
      type: string # Required - catalog|file
      properties: # Required - object{}
        catalog_name: # Required for catalog type
        schema_name: # Required for catalog type
        file_location: string # Required for file type - Volume path of the source data
  target_entity: # Required
    data_store: # Required
      type: string # Required - catalog
      properties:
        catalog_name: # Required
        schema_name: # Required
```

Full Specification
```yaml
<source_to_target_definition_1>: # Required
  source_entity: # Required
    data_store: # Required
      type: string # Required - catalog|file
      properties: # Required - object{}
        catalog_name: # Required for catalog type
        schema_name: # Required for catalog type
        table_name: # Required
        file_location: string # Required for file type - Volume path of the source data
        spark_options: object # Optional
    # if schema is undefined, all columns are read. If it's defined, the only the listed columns will be pulled, skipping undefined columns
    schema: # Optional - [object {}]
      - :
        column_name: # Optional
        type: string # Optional - The source column's data type
        nullable: boolean # Optional - Indicator if the source column can be a null value
        is_key: boolean # Optional - Indicator if the source column should be considered as a primary or surrogate key

  target_definition: # Required
    data_store: # Required
      type: string # Required - catalog
      properties: # Required - object{}
        catalog_name: # Required
        schema_name: # Required
        table_name: # Required
    # if schema_transform_map is undefined, all columns are written as-is. If defined, only the listed columns will be written, skipping undefined columns
    schema_transform_map:
      - :
        column_name: # Optional - Target column name to be written. If source_column_name is undefined, this value must match source
        source_column_name: # Optional - Map from a source column if changed on write to the target table
        type: string # Optional - If different from source, a cast will be attempted given the mapping in the Framework
        is_key: boolean # Optional - Indicator if the target column should be considered as a primary or surrogate key

  table_transform: # Optional
    dedup: # Optional
      enabled: boolean # Required
      properties:
        keys_override: [] # Optional - Override the primary or surrogate key defined in the above definitions for this transform
    cdc:
      enabled: boolean
      properties:
        mode: append
    # future? - hash_calculation: # Optional - Defines which columns to generate a new hash column from, if later comparison is needed
    #             enabled: boolean # Required
    #             properties:
    #             keys_override: [] # Optional - Override the primary or surrogate key defined in the above definitions for this transform
    <add_custom_transformations_here>: # Optional - Projects may optionally include custom transformations & add them to this list
  rules:
    bronze:
      <rule_severity_type>: # Required - Warn|Error
        <rule_type>: # Required - literal|derived
          <rule>: string # Required - SQL expression of rule to be ran (i.e 'id IS NOT NULL')

<source_to_target_definition_2>: # Optional - Allows for multiple definitions in a config file for logical groups without changing execution
...
```

For examples see:
* [Example Single Bronze Table Configuration JSON File](./bronze_table_definitions/example1_bronze_table_conf.json)
* [Example Multiple Bronze Table Configuration JSON File](./bronze_table_definitions/multiple_bronze_tables_conf.json)
* [Example Silver Table SQL File](./silver_table_definitions/example-silver.py)

## Asset Bundle, Workflow, & DLT Configuration
[Asset Bundle Overview](https://docs.databricks.com/en/dev-tools/bundles/settings.html)


## Testing
### Notebook Testing
Pull or create a branch for your work into your working Databricks instance. From there, write your notebook & run using the shared or personal compute as avialable. 
For DLT notebook testing, work as-is, but comment out @dlt(...) annotations as well as the `import dlt` but otherwise run as is. Before deployment & testing as a DLT just undo the comments & proceed as normal.

Under `test/`, there is a functional Asset Bundle & DLT pipeline setup for quick testing of new features or training on core concepts of the framework.
Note, that it's in development mode by default, & will deploy a seperate copy under your name automatically. You can view run & modify without collision. You can remove these artifacts by running `databricks bundle destroy -t dev -p dev` or for whatever target/profile you used to create them.
