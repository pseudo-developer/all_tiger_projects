# Databricks notebook source
# MAGIC %md
# MAGIC
# MAGIC #### Meta Data Medallion Framework 
# MAGIC
# MAGIC ##### Datasources: The **databricks** is a structured data processing framework designed to manage data ingestion, transformation, and aggregation across multiple layers (Bronze, Silver, Gold) in Databricks. It leverages modular scripts to ensure efficient data handling and processing, making it suitable for robust data pipelines.

# COMMAND ----------

# MAGIC %md
# MAGIC ##### Setup variables

# COMMAND ----------

dbutils.widgets.text('configuration_path', '', label='Path to Table Configuration Files')
dbutils.widgets.text('utils_path', '', label='Path to the Ingestion Framework Utils module')

# COMMAND ----------

# MAGIC %md
# MAGIC ##### Get input parameters

# COMMAND ----------

import sys, os
configuration_path = dbutils.widgets.get("configuration_path")
sys.path.append(os.path.abspath(dbutils.widgets.get('utils_path')+"/utils"))
from utils import helper

# COMMAND ----------

# MAGIC %md
# MAGIC The code retrieves a list of JSON configuration files from a specified directory. It defines a function, get_config_files, that checks the directory for files ending in .json and returns their paths. The main part of the code then calls this function

# COMMAND ----------

try:
    table_config_file_path_list = helper.get_config_files(configuration_path)
    print(table_config_file_path_list)
    dbutils.jobs.taskValues.set(
        key="table_config_file_path_list", value=table_config_file_path_list
    )
except Exception as e:
    print(e)
