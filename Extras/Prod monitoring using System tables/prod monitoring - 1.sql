-- Databricks notebook source
select hour(to_timestamp(('2025-01-17T05:59:00.000+00:00')))

-- COMMAND ----------

 SELECT
    `start_time`,
    `end_time`,
    `cluster_id`,
    `instance_id`,
    `driver`,
    `cpu_user_percent`,
    `cpu_system_percent`,
    `cpu_wait_percent`,
    `mem_used_percent`,
    `mem_swap_percent`,
    `network_sent_bytes`,
    `network_received_bytes`,
    DATE(`start_time`) AS `date`
  FROM
    `system`.`compute`.`node_timeline`
  WHERE
    HOUR(`start_time`) >= 3 AND HOUR(`start_time`) < 6 and cluster_id = '0722-195546-9bavpgv5'
  order by start_time desc
  

-- COMMAND ----------

SELECT
  *
FROM
  `system`.`lakeflow`.`job_run_timeline`
WHERE
  `job_id` = '218960856463815'
ORDER BY
  `period_start_time` DESC

-- COMMAND ----------

desc table system.lakeflow.job_run_timeline

-- COMMAND ----------

desc table system.lakeflow.job_task_run_timeline

-- COMMAND ----------

desc table system.compute.node_timeline

-- COMMAND ----------

-- DBTITLE 1,aggregated metrices
-- cell calculates various aggregated metrics for a specific cluster (cluster_id = '0722-195546-9bavpgv5') within a specific time window (3:00 AM to 6:00 AM UTC) for each day. The goal is to provide a summary of resource utilization and network activity during this period.

WITH DailyMetrics AS (
  SELECT
    start_time,
    end_time,
    cluster_id,
    instance_id,
    driver,
    cpu_user_percent,
    cpu_system_percent,
    cpu_wait_percent,
    mem_used_percent,
    mem_swap_percent,
    network_sent_bytes,
    network_received_bytes,
    DATE(start_time) AS date
  FROM
    system.compute.node_timeline
  WHERE
    HOUR(start_time) >= 3 AND HOUR(start_time) < 6 
),
AggregatedMetrics AS (
  SELECT
    date,
    cluster_id,
    instance_id,
    SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)) AS total_active_minutes,
    SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time))/60 AS total_active_hours,
    AVG(cpu_user_percent) AS avg_cpu_user_percent,
    AVG(cpu_system_percent) AS avg_cpu_system_percent,
    AVG(cpu_wait_percent) AS avg_cpu_wait_percent,
    AVG(mem_used_percent) AS avg_mem_used_percent,
    AVG(mem_swap_percent) AS avg_mem_swap_percent,
    MAX(cpu_user_percent) AS max_cpu_user_percent,
    MAX(cpu_system_percent) AS max_cpu_system_percent,
    MAX(cpu_wait_percent) AS max_cpu_wait_percent,
    MAX(mem_used_percent) AS max_mem_used_percent,
    MAX(mem_swap_percent) AS max_mem_swap_percent,
    SUM(network_sent_bytes) AS total_network_sent_bytes,
    SUM(network_received_bytes) AS total_network_received_bytes,
    SUM(network_sent_bytes) / (1024 * 1024 * 1024) AS total_network_sent_gb,
    SUM(network_received_bytes) / (1024 * 1024 * 1024) AS total_network_received_gb
  FROM
    DailyMetrics
  WHERE
    cluster_id = '0722-195546-9bavpgv5'
  GROUP BY
    date,
    cluster_id,
    instance_id
)
SELECT
  *
FROM
  AggregatedMetrics
ORDER BY
  date DESC


-- COMMAND ----------

WITH DailyMetrics AS (
  SELECT
    start_time,
    CASE
      WHEN end_time > make_timestamp(YEAR(start_time), MONTH(start_time), DAY(start_time), 6, 0, 0) THEN make_timestamp(YEAR(start_time), MONTH(start_time), DAY(start_time), 6, 0, 0)
      ELSE end_time
    END AS end_time,
    cluster_id,
    instance_id,
    driver,
    cpu_user_percent,
    cpu_system_percent,
    cpu_wait_percent,
    mem_used_percent,
    mem_swap_percent,
    network_sent_bytes,
    network_received_bytes,
    DATE(start_time) AS date
  FROM
    system.compute.node_timeline
  WHERE
    HOUR(start_time) >= 3 AND HOUR(start_time) < 6
    AND cluster_id = '0722-195546-9bavpgv5'
),
AggregatedMetrics AS (
  SELECT
    date,
    cluster_id,
    instance_id,
    SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)) AS total_active_minutes,
    SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)) / 60 AS total_active_hours,
    AVG(cpu_user_percent) AS avg_cpu_user_percent,
    AVG(cpu_system_percent) AS avg_cpu_system_percent,
    AVG(cpu_wait_percent) AS avg_cpu_wait_percent,
    AVG(mem_used_percent) AS avg_mem_used_percent,
    AVG(mem_swap_percent) AS avg_mem_swap_percent,
    MAX(cpu_user_percent) AS max_cpu_user_percent,
    MAX(cpu_system_percent) AS max_cpu_system_percent,
    MAX(cpu_wait_percent) AS max_cpu_wait_percent,
    MAX(mem_used_percent) AS max_mem_used_percent,
    MAX(mem_swap_percent) AS max_mem_swap_percent,
    SUM(network_sent_bytes) AS total_network_sent_bytes,
    SUM(network_received_bytes) AS total_network_received_bytes,
    SUM(network_sent_bytes) / (1024 * 1024 * 1024) AS total_network_sent_gb,
    SUM(network_received_bytes) / (1024 * 1024 * 1024) AS total_network_received_gb
  FROM
    DailyMetrics
  GROUP BY
    date,
    cluster_id,
    instance_id
),
final AS (
  SELECT * FROM AggregatedMetrics ORDER BY date DESC
)

SELECT 1 s_no, 'max_mem_used_percent greater_than_50' AS aggregation_type, COUNT(*)  FROM final WHERE max_mem_used_percent > 50
UNION
SELECT 2 s_no, 'max_cpu_system_percent greater_than_50' AS aggregation_type, COUNT(*) FROM final WHERE max_cpu_system_percent > 50
UNION
SELECT 3 s_no, 'max_cpu_user_percent greater_than_50' AS aggregation_type, COUNT(*) FROM final WHERE max_cpu_user_percent > 50

order by  s_no

-- COMMAND ----------

-- DBTITLE 1,idle hours
-- we are trying to calculate the idle time of a specific cluster (cluster_id = '0722-195546-9bavpgv5') for each day within a specific time window (3:00 AM to 6:00 AM UTC). The goal is to determine how much time the cluster was idle during this period

-- This CTE calculates the idle time for each day and cluster.
-- It sums the duration (in minutes) where the combined CPU usage (cpu_user_percent + cpu_system_percent + cpu_wait_percent) is less than 1%. This threshold is used to approximate idle time.

WITH DailyMetrics AS (
  SELECT
    start_time,
    end_time,
    cluster_id,
    instance_id,
    driver,
    cpu_user_percent,
    cpu_system_percent,
    cpu_wait_percent,
    mem_used_percent,
    mem_swap_percent,
    network_sent_bytes,
    network_received_bytes,
    DATE(start_time) AS date
  FROM
    system.compute.node_timeline
  WHERE
    HOUR(start_time) >= 3 AND HOUR(start_time) < 6
    AND cluster_id = '0722-195546-9bavpgv5'
),
IdleTimeCTE AS (
  SELECT
    date,
    cluster_id,
    SUM(
      CASE
        WHEN cpu_user_percent + cpu_system_percent + cpu_wait_percent < 1 THEN TIMESTAMPDIFF(MINUTE, start_time, end_time)
        ELSE 0
      END
    ) AS idle_time_minutes
  FROM
    DailyMetrics
  GROUP BY
    date,
    cluster_id
)
SELECT
  date,
  cluster_id,
  idle_time_minutes,
  idle_time_minutes / 60 AS idle_time_hours
FROM
  IdleTimeCTE
ORDER BY
  date DESC;

-- COMMAND ----------

WITH ClusterTimeCTE AS (
  SELECT
    `cluster_id`,
    `change_time`,
    `worker_count`,
    `max_autoscale_workers`,
    LAG(`change_time`) OVER (
      PARTITION BY `cluster_id`
      ORDER BY
        `change_time`
    ) AS previous_change_time
  FROM
    `system`.`compute`.`clusters`
  WHERE
    `cluster_id` = '0722-195546-9bavpgv5'
),
IdleTimeCTE AS (
  SELECT
    `cluster_id`,
    SUM(
      CASE
        WHEN `worker_count` = 0 THEN UNIX_TIMESTAMP(`change_time`) - UNIX_TIMESTAMP(`previous_change_time`)
        ELSE 0
      END
    ) AS idle_time_seconds
  FROM
    ClusterTimeCTE
  GROUP BY
    `cluster_id`
),
PeakUtilizationTimeCTE AS (
  SELECT
    `cluster_id`,
    SUM(
      CASE
        WHEN `worker_count` = `max_autoscale_workers` THEN UNIX_TIMESTAMP(`change_time`) - UNIX_TIMESTAMP(`previous_change_time`)
        ELSE 0
      END
    ) AS peak_utilization_time_seconds
  FROM
    ClusterTimeCTE
  GROUP BY
    `cluster_id`
)
SELECT
  `IdleTimeCTE`.`cluster_id`,
  `idle_time_seconds`,
  `peak_utilization_time_seconds`
FROM
  IdleTimeCTE
  JOIN PeakUtilizationTimeCTE ON `IdleTimeCTE`.`cluster_id` = `PeakUtilizationTimeCTE`.`cluster_id`;