# Databricks notebook source
# DBTITLE 1,widgets
dbutils.widgets.dropdown("env", "dev", ["dev", "qa", "stg", "prod"], "Environment")
env = dbutils.widgets.get("env")
dbutils.widgets.text("catalog_name_prefix", "ces_agency_agency_profile_", "Catalog Name Prefix")
catalog_name_prefix = dbutils.widgets.get("catalog_name_prefix")

# COMMAND ----------

# DBTITLE 1,catalog creation
# create the catalog if it doesn't exist
catalog_name = f"{catalog_name_prefix}_{env}"
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog_name};")

# COMMAND ----------

# DBTITLE 1,Setup for permissions
# Permission Setup
permission_env_name_lookup = {
    "dev": "dev",
    "qa": "qa",
    "stg": "stage",
    "prod": "prod"
}

# build a map of permissions & what role should have that permission. Add/remove as needed
# TODO: Currently untested/unsupported is modifying this list to be run on an existing catalog setup.
# - will need to check if the permission exists, isn't present in this dictionary & remove?
# - also looking into Terraform to automate this as a future enhancement
permissions_lookup = {
    "USE CATALOG": ["users", "developer", "admin", "ws-admin"],
    "USE SCHEMA": ["users", "developer", "admin", "ws-admin"],
    "SELECT": ["users", "developer", "admin", "ws-admin"],
    "READ VOLUME": ["users", "developer", "admin", "ws-admin"],
    "EXECUTE": ["users", "developer", "admin", "ws-admin"],
    "BROWSE": ["users", "developer", "admin", "ws-admin"],
    "ALL PRIVILEGES": ["admin", "ws-admin"],
    "APPLY TAG": ["developer"],
    "CREATE MATERIALIZED VIEW": ["developer"],
    "CREATE FUNCTION": ["developer"],
    "CREATE TABLE": ["developer"],
    "CREATE MODEL": ["developer"],
    "CREATE SCHEMA": ["developer"],
    "CREATE VOLUME": ["developer"],
    "MODIFY": ["developer"],
    "WRITE VOLUME": ["developer"]
}

# COMMAND ----------

permission_env = permission_env_name_lookup.get(env)
print(f"Setting permissions for {permission_env}")

for role, group_suffix in permissions_lookup.items():
    for group in group_suffix:
        group_name = f"`az-adv-dnap-eus2-adb-01-i1-{permission_env}-{group}`"
        sql_command = f"GRANT {role} ON CATALOG {catalog_name} TO {group_name};"
        print(sql_command)
        spark.sql(sql_command)
        print(sql_command)
