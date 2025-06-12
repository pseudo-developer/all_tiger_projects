# Databricks notebook source
# MAGIC %md
# MAGIC This notebook should be run manually to manage SQL alerting. You can use this notebook to create queries, alerts, and then automatically set up a Teams or email alerting workflow based on the results of the SQL. Specify your configuration file in the notebook parameter. If you run this notebook again for the same query/alert/workflow, it should modify the existing instead of creating a new one (idempotency).
# MAGIC
# MAGIC This notebook is distinct from the workflow-status-notifier, which just can be added as a task to an existing Databricks workflow, and is reponsible for sending messages about the workflow current status. Instead, this notebook is for alerting based off an isolated SQL query you provide.

# COMMAND ----------

dbutils.widgets.text('JSON File', 'configs/example-config.json')
json_file = dbutils.widgets.get('JSON File')


# COMMAND ----------

# DBTITLE 1,Define the Config model
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel
from typing import List, Optional, Literal, Union
from databricks.sdk.service import sql


class CamelModel(BaseModel):
    class Config:
        alias_generator = to_camel
        populate_by_name = True


class QueryModel(CamelModel):
    display_name: str = Field(..., description="A display name for the query.")
    description: Optional[str] = Field(None, description="A description of the query")
    sql: str = Field(..., description="The SQL you want to run for the alert. Note: If you specify both email and Teams alerting, the query may be executed once for each type of alerting")


class AlertModel(CamelModel):
    display_name: str = Field(..., description="A display name for the alert.", examples=["Missing Instep File Alert"])
    column_name: str = Field(..., description="The column from the query to compare against the operand value.")
    operator: Literal["EQUAL", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "IS_NULL", "LESS_THAN", "LESS_THAN_OR_EQUAL", "NOT_EQUAL"]
    operand_value: Union[bool, float, str, None] = Field(..., description="The value to compare against the column\'s value.")


class EmailConfigModel(CamelModel):
    subject: Optional[str] = Field(None, description='custom subject to override Databricks default')
    body: Optional[str] = Field(None, description='custom body to override Databricks default. See https://docs.databricks.com/en/sql/user/alerts/index.html for details on what custom fields can be used, such as {{QUERY_RESULT_TABLE}}.')
    notification_destinations: List[str] = Field(description="Set up a system notification destination at {databricks_workspace_url}/settings/workspace/notifications/notification-destinations, then use one or more of their display names here", examples=["Instep Missing File Alerts Group"]),


class TeamsConfigModel(CamelModel):
    workflow_url: str
    title: str
    body: Optional[str] = Field(None)
    show_alert_result: Optional[bool] = Field(False)


class NotificationModel(CamelModel):
    cron_expression: str
    timezone_id: str
    teams_configs: Optional[TeamsConfigModel] = Field(None)
    email_configs: Optional[EmailConfigModel] = Field(None)


class AlertConfigModel(CamelModel):
    query: QueryModel
    alert: AlertModel
    notification: NotificationModel


class AlertConfigListModel(CamelModel):
    configs: List[AlertConfigModel]


# COMMAND ----------

# DBTITLE 1,Helper Functions
from databricks.sdk import WorkspaceClient
from copy import copy


client = WorkspaceClient()


def get_workspace_url():
    # dbutils.notebook.entry_point.getDbutils().notebook().getContext().tags().get("browserHostName").get()
    # the method above might work but we don't have permission so I'm hard coding something
    catalog_urls = {
        'dnap_dev': 'https://adb-4661267993302765.5.azuredatabricks.net',
        'dnap_qa': 'https://adb-7069523072644634.14.azuredatabricks.net',
        'dnap_prod': 'https://adb-372782409553294.14.azuredatabricks.net'
    }
    catalog = spark.catalog.currentCatalog()
    try:
        return catalog_urls[catalog]
    except KeyError:
        raise Exception(f'Unknown catalog: {catalog}')


def get_url_for_alert(alert_id: str):
    return get_workspace_url() + '/sql/alerts/' + alert_id


def get_url_for_query(query_id: str):
    return get_workspace_url() + '/sql/editor/' + query_id


def get_url_for_job(job_id: str):
    return get_workspace_url() + '/jobs/' + job_id + '/tasks'


def get_job_by_alert_name(alert_name: str):
    """Retrieve a job with a specific alert_name tag."""
    for job in client.jobs.list():
        if job_tags := job.settings.tags:
            if job_tags.get("alert_name") == alert_name:
                return client.jobs.get(job.job_id)
    return None


def get_cluster_by_name(cluster_name: str):
    """Retrieve a cluster with a specific name."""
    for cluster in client.clusters.list():
        if cluster.cluster_name == cluster_name:
            return cluster
    raise Exception(f'Cluster {cluster_name} could not be found')


def convert_to_alert_operand_value(value: Union[bool, float, str, None]) -> sql.AlertOperandValue:
    if isinstance(value, bool):
        return sql.AlertOperandValue(bool_value=value)
    elif isinstance(value, float):
        return sql.AlertOperandValue(double_value=value)
    elif isinstance(value, str):
        return sql.AlertOperandValue(string_value=value)
    else:
        return sql.AlertOperandValue()

# COMMAND ----------

# DBTITLE 1,Creating and Updating resources
from typing import Union

from databricks.sdk.service import sql, jobs, settings


def get_or_create_query(display_name: str, query_text: str = None, description: str = None):
    current_catalog = spark.catalog.currentCatalog()
    if not (srcs := client.data_sources.list()):
        raise Exception('We should have data sources...not sure what is happening')
    warehouse_id = srcs[0].warehouse_id  # TODO: pick a more consistent warehouse

    # https://databricks-sdk-py.readthedocs.io/en/latest/workspace/sql/queries.html
    for query in client.queries.list():
        if query.display_name == display_name:
            # update query text or description if necessary
            query_url = get_url_for_query(query.id)
            print(f"Query '{display_name}' already exists.")
            displayHTML(f"<a href='{query_url}' target='_blank'>{query_url}</a><br>")

            query_request = sql.UpdateQueryRequestQuery()
            update_mask_list = []
            if query_text and query.query_text != query_text:
                query_request.query_text = query_text
                update_mask_list.append("query_text")
            if description and query.description != description:
                query_request.description = description
                update_mask_list.append("description")
            if not update_mask_list:
                # nothing to update
                return query
            update_mask = ','.join(update_mask_list)
            query = client.queries.update(
                id=query.id,
                query=query_request,
                update_mask=update_mask
            )
            print(f'Updated {update_mask}')
            return query
            
    # query was not found, create it
    query = client.queries.create(
        query=sql.CreateQueryRequestQuery(
            display_name=display_name,
            warehouse_id=warehouse_id,
            description=description,
            query_text=query_text
        )
    )
    query_url = get_url_for_query(query.id)
    print(f"Created new query '{display_name}'.")
    displayHTML(f"<br><a href='{query_url}' target='_blank'>{query_url}</a><br>")
    return query


def get_or_create_alert(display_name: str, query_id: str | None = None, column_name: str | None = None, operator: sql.AlertOperator | None = None, operand_value: sql.AlertOperandValue | None = None, custom_subject: str | None = None, custom_body: str | None = None):
    
    if not all(v is None for v in [column_name, operator, operand_value]) and \
       not all(v is not None for v in [column_name, operator, operand_value]):
        raise ValueError("You must provide either all three parameters (column_name, operator, operand_value) or none of them.")
    
    for alert in client.alerts.list():
        if alert.display_name == display_name:
            alert_url = get_url_for_alert(alert.id)
            print(f"Alert '{display_name}' already exists.")
            displayHTML(f"<br><a href='{alert_url}' target='_blank'>{alert_url}</a><br>")
            
            alert_request = sql.UpdateAlertRequestAlert()
            update_mask_list = []
            
            column_name_changed = column_name and column_name != alert.condition.operand.column.name
            operator_changed = operator and operator != alert.condition.op
            operand_value_changed = operand_value and operand_value != alert.condition.threshold.value

            if query_id and alert.query_id != query_id:
                alert_request.query_id = query_id
                update_mask_list.append("query_id")
            if column_name_changed or operator_changed or operand_value_changed:
                alert_request.condition = sql.AlertCondition(
                    operand=sql.AlertConditionOperand(
                        column=sql.AlertOperandColumn(name=column_name)
                    ),
                    op=operator,
                    threshold=sql.AlertConditionThreshold(value=operand_value)
                )
                update_mask_list.append("condition")
            if custom_subject and alert.custom_subject != custom_subject:
                update_mask_list.append("custom_subject")
                alert_request.custom_subject = custom_subject
            if custom_body and alert.custom_body != custom_body:
                update_mask_list.append("custom_body")
                alert_request.custom_body = custom_body
            # the code below should work based on this class definition...
            # https://github.com/databricks/databricks-sdk-py/blob/980166030c688e08a52d0f55389abd766f1d928d/databricks/sdk/service/sql.py#L2682
            # but its breaking with notify_on_ok AttributeError. could be version problem?
            
            # if alert.notify_on_ok != notify_on_ok:
            #     update_mask_list.append("notify_on_ok")
            #     alert_request.notify_on_ok = notify_on_ok
            if not update_mask_list:
                # nothing to update
                return alert
            
            update_mask = ','.join(update_mask_list)
            alert = client.alerts.update(
                id=alert.id,
                alert=alert_request,
                update_mask=update_mask
            )
            print(f'Updated {update_mask}')
            return alert
        
    # https://databricks-sdk-py.readthedocs.io/en/latest/workspace/sql/alerts.html
    # https://github.com/databricks/databricks-sdk-py/blob/980166030c688e08a52d0f55389abd766f1d928d/databricks/sdk/service/sql.py#L642
    request = sql.CreateAlertRequestAlert(
        query_id=query_id,
        condition=sql.AlertCondition(
            operand=sql.AlertConditionOperand(
                column=sql.AlertOperandColumn(name=column_name)
            ),
            op=operator,
            threshold=sql.AlertConditionThreshold(value=operand_value)
        ),
        custom_body=custom_body,
        custom_subject=custom_subject,
        display_name=display_name
    )


    alert = client.alerts.create(alert=request)
    alert_url = get_url_for_alert(alert.id)
    print(f"Created new alert '{display_name}'.")
    displayHTML(f"<br><a href='{alert_url}' target='_blank'>{alert_url}</a><br>")
    return alert


def update_job(job, email_task=None, notebook_task=None, cron_expression=None, timezone_id=None):
    """Update an existing job with new settings."""
    update_mask_list = []
    fields_to_remove = []
    cluster = get_cluster_by_name('Medium Shared Compute Cluster')

    if cron_expression and job.settings.schedule.quartz_cron_expression != cron_expression:
        update_mask_list.append("cron expression")
    if timezone_id and job.settings.schedule.timezone_id != timezone_id:
        update_mask_list.append("timezone_id")
    job.settings.schedule = jobs.CronSchedule(
        quartz_cron_expression=cron_expression,
        timezone_id=timezone_id
    )

    tasks = job.settings.tasks
    if email_task:
        email_task_found = False
        for task in tasks:
            if task.task_key == 'email_alert_task':
                if sorted([subscription.destination_id for subscription in task.sql_task.alert.subscriptions]) != sorted([subscription.destination_id for subscription in email_task.alert.subscriptions]):
                    task.sql_task.alert.subscriptions = email_task.alert.subscriptions
                    update_mask_list.append("notification_destination_ids")
                    break
                email_task_found = True
        if not email_task_found:
            tasks.append(jobs.Task(
                task_key='email_alert_task',
                description='Send an email alert if the query condition is met',
                sql_task=email_task
            ))
    elif tasks_to_remove := [task for task in tasks if task.task_key == 'email_alert_task']:
        fields_to_remove.append('tasks/email_alert_task')
        print('Removing email_alert_task because it was not specified in the configs')
        for task in tasks_to_remove:
            tasks.remove(task)

    if notebook_task:
        notebook_task_found = False
        for task in tasks:
            if task.task_key == 'teams_alert_task':
                task.notebook_task.base_parameters = notebook_task.base_parameters
                if task.notebook_task.base_parameters.get("teams_workflow_url") != notebook_task.base_parameters.get("teams_workflow_url"):
                    update_mask_list.append("teams_workflow_url")
                if task.notebook_task.base_parameters.get("message_title") != notebook_task.base_parameters.get("message_title"):
                    update_mask_list.append("message_title")
                if task.notebook_task.base_parameters.get("message_body") != notebook_task.base_parameters.get("message_body"):
                    update_mask_list.append("message_body")
                if task.notebook_task.base_parameters.get("show_alert_result") != notebook_task.base_parameters.get("show_alert_result"):
                    update_mask_list.append("show_alert_result")
                notebook_task_found = True
        if not notebook_task_found:
            tasks.append(jobs.Task(
                task_key='teams_alert_task',
                description='Send a Teams alert if the query condition is met',
                notebook_task=notebook_task,
                existing_cluster_id=cluster.cluster_id
            ))
    elif tasks_to_remove := [task for task in tasks if task.task_key == 'teams_alert_task']:
        fields_to_remove.append('tasks/teams_alert_task')
        print('Removing teams_alert_task because it was not specified in the configs')
        tasks_to_remove = [task for task in tasks if task.task_key == 'teams_alert_task']
        for task in tasks_to_remove:
            tasks.remove(task)


    client.jobs.update(
        job_id=job.job_id,
        fields_to_remove=fields_to_remove,
        new_settings=job.settings
    )

    if update_mask_list:
        print(f"Updated {', '.join(update_mask_list)}")
        
    return job
    

def create_job(alert_display_name: str, email_task=None, notebook_task=None, cron_expression=None, timezone_id=None):
    """Create a new job with the provided settings."""
    tasks = []
    messages = []
    cluster = get_cluster_by_name('Medium Shared Compute Cluster')

    if notebook_task:
        tasks.append(jobs.Task(
            task_key='teams_alert_task',
            description='Send a Teams alert if the query condition is met',
            notebook_task=notebook_task,
            existing_cluster_id=cluster.cluster_id
        ))
        messages.append('a Teams notification')
    if email_task:
        # make the email task wait for the teams task, if it exists. This is to avoid any potential issues with the seconds_to_retrigger causing the Teams job to not send a message.
        run_if = jobs.RunIf(jobs.RunIf.ALL_DONE) if notebook_task else None
        depends_on = [jobs.TaskDependency(task_key='teams_alert_task')] if notebook_task else None

        tasks.append(jobs.Task(
            task_key='email_alert_task',
            description='Send an email alert if the query condition is met',
            sql_task=email_task,
            run_if=run_if,
            depends_on=depends_on,
        ))
        messages.append('an email notification')

    message = ' and '.join(messages)

    create_response = client.jobs.create(
        edit_mode=jobs.JobEditMode.EDITABLE,  # or jobs.JobEditMode.UI_LOCKED
        max_concurrent_runs=1,
        tags={"alert_name": alert_display_name},
        name="Run Alert - " + alert_display_name,
        description=f'This job is responsible for running the alert {alert_display_name}, and sending {message} if the query condition is met. This job was created programmatically by the alerting module of the dnap ingestion framework.',
        schedule=jobs.CronSchedule(
            quartz_cron_expression=cron_expression,
            timezone_id=timezone_id
        ),
        git_source=jobs.GitSource(
            git_url='https://github.com/Advantage-Solutions/dnap-ingestion-framework',
            git_provider=jobs.GitProvider.GIT_HUB,
            git_branch='main'
        ),
        tasks=tasks
    )
    job = client.jobs.get(create_response.job_id)
    print(f"Created new job '{job.settings.name}'.")
    job_url = get_url_for_job(str(job.job_id))
    displayHTML(f"<br><a href='{job_url}' target='_blank'>{job_url}</a><br>")
    return job


def create_or_update_job(alert: sql.Alert, notification_destination_ids: list[str] | None = None, teams_workflow_url: str | None = None, message_title: str | None = None, message_body: str | None = None, show_alert_result: bool = False, cron_expression: str | None = None, timezone_id: str | None = None):
    warehouse_id = client.data_sources.list()[0].warehouse_id  # TODO: pick a more consistent warehouse
    email_task = None
    notebook_task = None

    if notification_destination_ids:
        email_task = jobs.SqlTask(
            alert=jobs.SqlTaskAlert(
                alert_id=alert.id,
                subscriptions=[
                    jobs.SqlTaskSubscription(destination_id=notification_destination_id)
                    for notification_destination_id in notification_destination_ids
                ]
            ),
            warehouse_id=warehouse_id
        )

    if teams_workflow_url:
        notebook_task = jobs.NotebookTask(
            notebook_path="alerting/query-notifier",
            base_parameters={
                "alert_id": alert.id,
                "teams_workflow_url": teams_workflow_url,
                "message_title": message_title,
                "message_body": message_body,
                "show_alert_result": show_alert_result
            }
        )


    if job := get_job_by_alert_name(alert.display_name):
        if not email_task and not notebook_task:
            # No tasks specified, delete the job
            client.jobs.delete(job.id)
            print(f"Deleted job '{job.settings.name}' because no tasks were specified for it.")
            return
        # Update the existing job
        job_url = get_url_for_job(str(job.job_id))
        print(f"Job '{job.settings.name}' already exists.")
        displayHTML(f"<br><a href='{job_url}' target='_blank'>{job_url}</a><br>")
        return update_job(job, email_task=email_task, notebook_task=notebook_task, cron_expression=cron_expression, timezone_id=timezone_id)

    # Create a new job
    return create_job(alert.display_name, email_task=email_task, notebook_task=notebook_task, cron_expression=cron_expression, timezone_id=timezone_id)


def get_notification_destinations(display_names: list[str]) -> list[settings.NotificationDestination]:
    destinations = list(client.notification_destinations.list())
    found_destinations = []
    missing_display_names = []

    for display_name in display_names:
        for destination in destinations:
            if destination.display_name == display_name:
                found_destinations.append(destination)
                break
        else:
            missing_display_names.append(display_name)

    if missing_display_names:
        missing_names_str = ", ".join(missing_display_names)
        raise Exception(f"Notification destinations \"{missing_names_str}\" not found. You must first create them at {get_workspace_url()}/settings/workspace/notifications/notification-destinations")

    return found_destinations





# COMMAND ----------

# DBTITLE 1,Main

def main_work():
    with open(json_file, 'r') as f:
        json_data = f.read()

    configs = AlertConfigListModel.parse_raw(json_data).configs

    for config in configs:
        notification_destinations, subject, body, teams_workflow_url, teams_title, teams_body, teams_show_alert_result = [], None, None, None, None, None, None
        if email_configs := config.notification.email_configs:
            subject = email_configs.subject
            body = email_configs.body
            notification_destinations = email_configs.notification_destinations
        if teams_configs := config.notification.teams_configs:
            teams_workflow_url = teams_configs.workflow_url
            teams_title = teams_configs.title
            teams_body = teams_configs.body
            teams_show_alert_result = teams_configs.show_alert_result


        # convert simple types to databricks types
        alert_operator = sql.AlertOperator[config.alert.operator]
        alert_operand_value = convert_to_alert_operand_value(config.alert.operand_value)

        notification_destinations = get_notification_destinations(notification_destinations)


        query = get_or_create_query(config.query.display_name, config.query.sql, config.query.description)
        alert = get_or_create_alert(
            display_name=config.alert.display_name,
            query_id=query.id,
            column_name=config.alert.column_name,
            operator=alert_operator,
            operand_value=alert_operand_value,
            custom_subject=subject,
            custom_body=body
        )
        job = create_or_update_job(
            alert=alert,
            notification_destination_ids=[destination.id for destination in notification_destinations],
            teams_workflow_url=teams_workflow_url,
            message_title=teams_title,
            message_body=teams_body,
            show_alert_result=teams_show_alert_result,
            cron_expression=config.notification.cron_expression,
            timezone_id=config.notification.timezone_id
        )


if __name__ == "__main__":
    main_work()
