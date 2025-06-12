-- Databricks notebook source
-- DBTITLE 1,Nodes active per minute - 9-12
SELECT
  start_time,
  start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
  COUNT(DISTINCT instance_id) AS active_nodes
FROM
  system.compute.node_timeline
WHERE
  cluster_id = '0722-195546-9bavpgv5'
  AND DATE(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) = '2025-01-23'
  AND HOUR(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) >= 9
  AND HOUR(start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES) < 12
GROUP BY
  start_time
ORDER BY
  start_time;

-- COMMAND ----------

-- DBTITLE 1,pts-jet on 2025-01-23
-- job_id = '218960856463815' and run_id = '530572671410474'

-- Step 1: Retrieve job run details for run of pts-jet on 2025-01-23
WITH JobRunDetails AS (
  SELECT
    MIN(period_start_time) AS period_start_time,
    MAX(period_end_time) AS period_end_time
  FROM
    system.lakeflow.job_run_timeline
  WHERE
    job_id = '218960856463815'
    AND run_id = '530572671410474'
),

-- Step 2: Retrieve relevant resource utilization data
NodeTimeline AS (
  SELECT
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
    AND start_time >= (SELECT period_start_time FROM JobRunDetails)
    AND start_time <= (SELECT period_end_time FROM JobRunDetails)
)

-- Step 3: Select the final result
SELECT
  start_time_ist,
  -- start_time,
  end_time_ist,
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
  NodeTimeline
ORDER BY
  start_time_ist;

-- COMMAND ----------

-- DBTITLE 1,Get 4 quadrants created for the run of pts-jet 2025-01-23
-- MAGIC %python
-- MAGIC spark.sql("""
-- MAGIC           
-- MAGIC  WITH JobRunDetails AS (
-- MAGIC   SELECT
-- MAGIC     MIN(period_start_time) AS period_start_time,
-- MAGIC     MAX(period_end_time) AS period_end_time
-- MAGIC   FROM
-- MAGIC     system.lakeflow.job_run_timeline
-- MAGIC   WHERE
-- MAGIC     job_id = '218960856463815'
-- MAGIC     AND run_id = '530572671410474'
-- MAGIC ),
-- MAGIC JobRunDuration AS (
-- MAGIC   SELECT
-- MAGIC     period_start_time,
-- MAGIC     period_end_time,
-- MAGIC     TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) AS total_duration_seconds,
-- MAGIC     TIMESTAMPADD(SECOND, TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_1_end,
-- MAGIC     TIMESTAMPADD(SECOND, 2 * TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_2_end,
-- MAGIC     TIMESTAMPADD(SECOND, 3 * TIMESTAMPDIFF(SECOND, period_start_time, period_end_time) / 4, period_start_time) AS quadrant_3_end,
-- MAGIC     period_end_time AS quadrant_4_end
-- MAGIC   FROM
-- MAGIC     JobRunDetails
-- MAGIC )
-- MAGIC -- SELECT * FROM JobRunDuration
-- MAGIC ,NodeTimeline AS (
-- MAGIC   SELECT
-- MAGIC     CASE
-- MAGIC       WHEN start_time <= (SELECT quadrant_1_end FROM JobRunDuration) THEN 'q1'
-- MAGIC       WHEN start_time <= (SELECT quadrant_2_end FROM JobRunDuration) THEN 'q2'
-- MAGIC       WHEN start_time <= (SELECT quadrant_3_end FROM JobRunDuration) THEN 'q3'
-- MAGIC       ELSE 'q4'
-- MAGIC     END AS quadrant,
-- MAGIC     -- start_time,
-- MAGIC     start_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS start_time_ist,
-- MAGIC     end_time + INTERVAL 5 HOURS + INTERVAL 30 MINUTES AS end_time_ist,
-- MAGIC     instance_id,
-- MAGIC     driver,
-- MAGIC     cpu_user_percent,
-- MAGIC     cpu_system_percent,
-- MAGIC     cpu_wait_percent,
-- MAGIC     mem_used_percent,
-- MAGIC     mem_swap_percent,
-- MAGIC     network_sent_bytes,
-- MAGIC     network_received_bytes
-- MAGIC   FROM
-- MAGIC     system.compute.node_timeline
-- MAGIC   WHERE
-- MAGIC     cluster_id = '0722-195546-9bavpgv5'
-- MAGIC     AND start_time >= (SELECT period_start_time FROM JobRunDuration)
-- MAGIC     AND start_time <= (SELECT period_end_time FROM JobRunDuration)
-- MAGIC     AND driver = 'false'
-- MAGIC )
-- MAGIC select * from NodeTimeline order by start_time_ist;
-- MAGIC           
-- MAGIC           """).createOrReplaceTempView("quadrant_level_pts_jet_20250123")

-- COMMAND ----------

-- DBTITLE 1,display quadrant_level_pts_jet_20250123
select * from quadrant_level_pts_jet_20250123

-- COMMAND ----------

-- DBTITLE 1,aggreagted resource utilisation per quadrant
-- MAGIC %python
-- MAGIC df_aggr = spark.sql("""
-- MAGIC SELECT
-- MAGIC     quadrant,
-- MAGIC     AVG(cpu_user_percent) AS avg_cpu_user_percent,
-- MAGIC     MIN(cpu_user_percent) AS min_cpu_user_percent,
-- MAGIC     MAX(cpu_user_percent) AS max_cpu_user_percent,
-- MAGIC     
-- MAGIC     AVG(cpu_system_percent) AS avg_cpu_system_percent,
-- MAGIC     MIN(cpu_system_percent) AS max_cpu_system_percent,
-- MAGIC     MAX(cpu_system_percent) AS min_cpu_system_percent,
-- MAGIC
-- MAGIC     AVG(cpu_wait_percent) AS avg_cpu_wait_percent,
-- MAGIC     MIN(cpu_wait_percent) AS min_cpu_wait_percent,
-- MAGIC     MAX(cpu_wait_percent) AS max_cpu_wait_percent,
-- MAGIC
-- MAGIC     AVG(mem_used_percent) AS avg_mem_used_percent,
-- MAGIC     MIN(mem_used_percent) AS min_mem_used_percent,
-- MAGIC     MAX(mem_used_percent) AS max_mem_used_percent,
-- MAGIC
-- MAGIC     AVG(mem_swap_percent) AS avg_mem_swap_percent,
-- MAGIC     MIN(mem_swap_percent) AS min_mem_swap_percent,
-- MAGIC     MAX(mem_swap_percent) AS max_mem_swap_percent,
-- MAGIC     
-- MAGIC     SUM(network_sent_bytes) AS total_network_sent_bytes,
-- MAGIC     SUM(network_received_bytes) AS total_network_received_bytes
-- MAGIC   FROM
-- MAGIC     quadrant_level_pts_jet_20250123
-- MAGIC   GROUP BY
-- MAGIC     quadrant
-- MAGIC   order by quadrant
-- MAGIC """)
-- MAGIC
-- MAGIC df_aggr.createOrReplaceTempView("quadrant_level_pts_jet_20250123_aggr_summary")

-- COMMAND ----------

-- DBTITLE 1,find average active nodes per quadrant
-- MAGIC %python
-- MAGIC spark.sql("""
-- MAGIC select  quadrant, count(distinct instance_id) as active_nodes_per_quadrant
-- MAGIC from quadrant_level_pts_jet_20250123
-- MAGIC group by quadrant_level_pts_jet_20250123.quadrant
-- MAGIC order by quadrant_level_pts_jet_20250123.quadrant
-- MAGIC
-- MAGIC -- limit 1
-- MAGIC """).createOrReplaceTempView("quadrant_level_pts_jet_20250123_active_nodes")

-- COMMAND ----------

select 
quadrant_level_pts_jet_20250123_active_nodes.*
, quadrant_level_pts_jet_20250123_aggr_summary.* EXCEPT (quadrant_level_pts_jet_20250123_aggr_summary.quadrant)
from quadrant_level_pts_jet_20250123_active_nodes inner join quadrant_level_pts_jet_20250123_aggr_summary
on quadrant_level_pts_jet_20250123_active_nodes.quadrant = quadrant_level_pts_jet_20250123_aggr_summary.quadrant
order by quadrant_level_pts_jet_20250123_active_nodes.quadrant

-- COMMAND ----------

-- DBTITLE 1,active nodes per minute
select  start_time_ist, count(distinct instance_id) as active_nodes_per_minute
from quadrant_level_pts_jet_20250123
group by start_time_ist
order by start_time_ist

limit 1

-- COMMAND ----------

desc table system.compute.node_timeline

-- COMMAND ----------

desc table system.lakeflow.job_task_run_timeline

-- COMMAND ----------

SELECT *
FROM system.lakeflow.job_task_run_timeline
 WHERE
    job_id = '218960856463815'
    AND job_run_id = '530572671410474'

-- COMMAND ----------

with q1_cte as (
  select * from quadrant_level_pts_jet_20250123 where quadrant = 'q1'
)
select * from q1_cte limit 1


-- COMMAND ----------

SELECT `AuditNo_PK`, `AuditServerDateTime`, `AuditUser`, `AuditAction`, `PayrollExportNo_PK`, `TimeNo_FK`, `EmployeeNo_FK`, `EmployeeExpenseNo_FK`, `PayrollApprovalUserNo_FK`, `JobNo_FK`, `BreakTimeNo_FK`, `AssemblyItemNo_FK`, `EmployeeID`, `BeginDateTime`, `EndDateTime`, `ElementName`, `EmpCompRateBasis`, `Activity`, `Quantity`, `Rate`, `PayrollApprovalDate`, `WorkedDepartment`, `JobID`, `StateWorked`, `Duration`, `Pay`, `PayrollDate`, `CreateDate`, `CreateUserNo_FK`, `ModifyDate`, `ModifyUserNo_FK`, `TravelDuration`, `PiecePayItemNo_FK` FROM foreign_panama_ptsjet_rw5_prod.dbo.zzAudit_PayrollExport

-- COMMAND ----------

-- MAGIC %python
-- MAGIC query = """
-- MAGIC SELECT `AuditNo_PK`, `AuditServerDateTime`, `AuditUser`, `AuditAction`, `PayrollExportNo_PK`, `TimeNo_FK`, `EmployeeNo_FK`, `EmployeeExpenseNo_FK`, `PayrollApprovalUserNo_FK`, `JobNo_FK`, `BreakTimeNo_FK`, `AssemblyItemNo_FK`, `EmployeeID`, `BeginDateTime`, `EndDateTime`, `ElementName`, `EmpCompRateBasis`, `Activity`, `Quantity`, `Rate`, `PayrollApprovalDate`, `WorkedDepartment`, `JobID`, `StateWorked`, `Duration`, `Pay`, `PayrollDate`, `CreateDate`, `CreateUserNo_FK`, `ModifyDate`, `ModifyUserNo_FK`, `TravelDuration`, `PiecePayItemNo_FK` FROM foreign_panama_ptsjet_rw5_qa.dbo.zzAudit_PayrollExport
-- MAGIC """
-- MAGIC
-- MAGIC query_df = spark.sql(query)

-- COMMAND ----------

