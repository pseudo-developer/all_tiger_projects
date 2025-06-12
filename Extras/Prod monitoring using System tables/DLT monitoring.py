# Databricks notebook source
cluster_id = '0722-195546-9bavpgv5' 
run_date = '2025-03-17'
start_hr_ist = 9
end_hr_ist = 12
job_id = '218960856463815'
job_run_id = '641239358487344'


# DLT-SPECIFIC
cluster_id_dlt_2025_03_14 = '0314-053450-2nv0qb2b' 
run_date_dlt_2025_03_14 = '2025-03-14' 

# COMMAND ----------

spark.sql(f"""
SELECT
  start_time,
  start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
  COUNT(DISTINCT instance_id) AS active_nodes
FROM
  system.compute.node_timeline
WHERE
  cluster_id = '{cluster_id_dlt_2025_03_14}'
  AND DATE(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) = '{run_date_dlt_2025_03_14}'
  -- AND HOUR(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) >= {start_hr_ist}
  -- AND HOUR(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) < {end_hr_ist}
GROUP BY
  start_time
ORDER BY
  start_time;          
""").display()

# COMMAND ----------

spark.sql(f"""
          
 WITH JobRunDetails AS (
  SELECT
    MIN(period_start_time) AS period_start_time,
    MAX(period_end_time) AS period_end_time
  FROM
    system.lakeflow.job_run_timeline
  WHERE
    job_id = '{job_id}'
    AND run_id = '{job_run_id}'
),
JobRunDuration AS (
  SELECT
    period_start_time,
    period_end_time,
    TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) AS total_duration_seconds,
    TIMESTAMPADD(SECOND, TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_1_end,
    TIMESTAMPADD(SECOND, 2 * TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_2_end,
    TIMESTAMPADD(SECOND, 3 * TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_3_end,
    period_end_time AS quadrant_4_end
  FROM
    JobRunDetails
)
-- SELECT * FROM JobRunDuration
,NodeTimeline AS (
  SELECT
    CASE
      WHEN start_time <= (SELECT quadrant_1_end FROM JobRunDuration) THEN 'q1'
      WHEN start_time <= (SELECT quadrant_2_end FROM JobRunDuration) THEN 'q2'
      WHEN start_time <= (SELECT quadrant_3_end FROM JobRunDuration) THEN 'q3'
      ELSE 'q4'
    END AS quadrant,
    -- start_time,
    start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
    end_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS end_time_ist,
    instance_id,
    driver,
    cpu_user_percent,
    cpu_system_percent,
    cpu_wait_percent,
    mem_used_percent,
    mem_swap_percent,
    network_sent_bytes,
    network_received_bytes
  FROM
    system.compute.node_timeline
  WHERE
    cluster_id = '0722-195546-9bavpgv5'
    AND start_time >= (SELECT period_start_time FROM JobRunDuration)
    AND start_time <= (SELECT period_end_time FROM JobRunDuration)
    AND driver = 'false'
)
select * from NodeTimeline order by start_time_ist;
          
          """).createOrReplaceTempView('pts_jet_run_details_2025_03_18')

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT *
# MAGIC     -- CASE
# MAGIC     --   WHEN start_time <= (SELECT quadrant_1_end FROM JobRunDuration) THEN 'q1'
# MAGIC     --   WHEN start_time <= (SELECT quadrant_2_end FROM JobRunDuration) THEN 'q2'
# MAGIC     --   WHEN start_time <= (SELECT quadrant_3_end FROM JobRunDuration) THEN 'q3'
# MAGIC     --   ELSE 'q4'
# MAGIC     -- END AS quadrant,
# MAGIC     -- start_time,
# MAGIC     -- start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
# MAGIC     -- end_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS end_time_ist,
# MAGIC     -- instance_id,
# MAGIC     -- driver,
# MAGIC     -- cpu_user_percent,
# MAGIC     -- cpu_system_percent,
# MAGIC     -- cpu_wait_percent,
# MAGIC     -- mem_used_percent,
# MAGIC     -- mem_swap_percent,
# MAGIC     -- network_sent_bytes,
# MAGIC     -- network_received_bytes
# MAGIC   FROM
# MAGIC     system.compute.node_timeline
# MAGIC   WHERE
# MAGIC     cluster_id = '0314-053450-2nv0qb2b'
# MAGIC     -- AND start_time >= (SELECT period_start_time FROM JobRunDuration)
# MAGIC     -- AND start_time <= (SELECT period_end_time FROM JobRunDuration)
# MAGIC     -- AND driver = 'false'

# COMMAND ----------

cluster_id_dlt_2025_03_14 = '0722-195546-9bavpgv5'

spark.sql(f"""
SELECT *
--   distinct task_key
FROM
  system.lakeflow.job_task_run_timeline
WHERE
--   array_contains(compute_ids, '{cluster_id_dlt_2025_03_14}')
job_run_id = '641239358487344' 
and task_key = 'run_bronze_dlt' 

""").display()

# COMMAND ----------

# MAGIC %sql
# MAGIC WITH ClusterDuration AS (
# MAGIC     SELECT 
# MAGIC         cluster_id,
# MAGIC         MIN(start_time) AS min_start_time,
# MAGIC         MAX(end_time) AS max_end_time,
# MAGIC         MAX(end_time) - MIN(start_time) AS total_duration
# MAGIC     FROM system.compute.node_timeline
# MAGIC     WHERE cluster_id = '0314-053450-2nv0qb2b'
# MAGIC     GROUP BY cluster_id
# MAGIC )
# MAGIC ,quadrants as (
# MAGIC SELECT 
# MAGIC     t.cluster_id,
# MAGIC     t.start_time,
# MAGIC     t.end_time,
# MAGIC     t.start_time - cd.min_start_time AS time_since_start,
# MAGIC     cd.total_duration,
# MAGIC     CASE 
# MAGIC         WHEN (t.start_time - cd.min_start_time) <= cd.total_duration * 0.25 THEN 'Q1'
# MAGIC         WHEN (t.start_time - cd.min_start_time) <= cd.total_duration * 0.50 THEN 'Q2'
# MAGIC         WHEN (t.start_time - cd.min_start_time) <= cd.total_duration * 0.75 THEN 'Q3'
# MAGIC         ELSE 'Q4'
# MAGIC     END AS quadrant,
# MAGIC     start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
# MAGIC     end_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS end_time_ist,
# MAGIC     instance_id,
# MAGIC     driver,
# MAGIC     cpu_user_percent,
# MAGIC     cpu_system_percent,
# MAGIC     cpu_wait_percent,
# MAGIC     mem_used_percent,
# MAGIC     mem_swap_percent,
# MAGIC     network_sent_bytes,
# MAGIC     network_received_bytes
# MAGIC FROM system.compute.node_timeline t
# MAGIC JOIN ClusterDuration cd
# MAGIC     ON t.cluster_id = cd.cluster_id
# MAGIC )
# MAGIC SELECT * FROM quadrants order by quadrant
# MAGIC

# COMMAND ----------

