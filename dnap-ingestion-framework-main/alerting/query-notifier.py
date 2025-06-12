# Databricks notebook source
# MAGIC %md
# MAGIC This notebook checks if the conditions on a given alert are met, then sends a Teams message if so.
# MAGIC
# MAGIC The idea is to set up a workflow that will run this notebook according to whatever schedule is needed (such as every day at 5:00 am). There is a notebook that will create that workflow for you however.
# MAGIC
# MAGIC (Alerts have built in Teams notifications, but they use deprecated workflows, so this is our workaround until Databricks fixes that.)

# COMMAND ----------

alert_id = dbutils.widgets.get('alert_id')
workflow_url = dbutils.widgets.get('teams_workflow_url')

message_title = dbutils.widgets.get('message_title')
message_body = dbutils.widgets.get('message_body')
show_alert_result = dbutils.widgets.get('show_alert_result').lower() in ('true', '1', 't', 'y', 'yes')


# COMMAND ----------

# DBTITLE 1,Helper Functions
import json

from pyspark.sql import DataFrame
from databricks.sdk.service import sql


def get_threshold_value_from_condition(condition: sql.AlertCondition):
    if threshold := alert.condition.threshold:
        if value := threshold.value:
            if value.bool_value is not None:
                return value.bool_value
            if value.double_value is not None:
                if value.double_value.is_integer():
                    return int(value.double_value)
                else:
                    return value.double_value
            if value.string_value is not None:
                return value.string_value


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



card_payload = {
    "type": "message",
    "attachments": [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4",
                "body": [
                    {
                        "type": "Container",
                        "items": [
                            {
                                "type": "ColumnSet",
                                "columns": [
                                    {
                                        "type": "Column",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": "{message_title}",
                                                "wrap": True,
                                                "style": "heading",
                                                "size": "Large"
                                            }
                                        ],
                                        "width": 70,
                                        "horizontalAlignment": "Left",
                                        "selectAction": {
                                            "type": "Action.OpenUrl",
                                            "url": "{alert_url}"
                                        }
                                    },
                                    {
                                        "type": "Column",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": spark.catalog.currentCatalog(),
                                                "wrap": True,
                                                "isSubtle": True,
                                                "horizontalAlignment": "Right"
                                            }
                                        ],
                                        "width": 30,
                                        "horizontalAlignment": "Right"
                                    }
                                ]
                            }
                        ],
                        "style": "emphasis",
                        "showBorder": True,
                        "verticalContentAlignment": "Center",
                        "spacing": "Small"
                    }
                ]
            }
        }
    ]
}


def fill_in_card_details(alert: sql.Alert, df: DataFrame):
    column_name = alert.condition.operand.column.name
    threshold_value = get_threshold_value_from_condition(alert.condition)
    query_value = df.first()[column_name]

    card_body = card_payload['attachments'][0]['content']['body']
    if message_body:
        message_element = {
            "type": "TextBlock",
            "text": message_body,
            "wrap": True,
            "spacing": "Medium"
        }
        card_body.append(message_element)

    if show_alert_result:
        card_body.extend([
            {
                "type": "TextBlock",
                "text": "{alert_result}",
                "wrap": True,
                "color": "Attention"
            },
            {
                "type": "RichTextBlock",
                "inlines": [
                    {
                        "type": "TextRun",
                        "text": "(Alert is triggered if ",
                        "size": "Small",
                        "isSubtle": True
                    },
                    {
                        "type": "TextRun",
                        "text": "{condition_text}",
                        "size": "Small"
                    },
                    {
                        "type": "TextRun",
                        "text": ")",
                        "size": "Small",
                        "isSubtle": True
                    }
                ]
            }
        ])

    # calculate alert url, alert_result, and condition text
    if query_value is None:
        alert_result = f'{column_name} IS NULL'
    else:
        alert_result = f'{column_name} = {query_value}'

    string_mapping = {
        sql.AlertOperator.EQUAL: '=',
        sql.AlertOperator.GREATER_THAN: '>',
        sql.AlertOperator.GREATER_THAN_OR_EQUAL: '≥',
        sql.AlertOperator.LESS_THAN: '<',
        sql.AlertOperator.LESS_THAN_OR_EQUAL: '≤',
        sql.AlertOperator.NOT_EQUAL: '≠',
    }
    
    if alert.condition.op == sql.AlertOperator.IS_NULL:
        condition_text = f'{column_name} IS NULL'
    else:
        condition_text = column_name + ' ' + string_mapping[alert.condition.op] + ' ' + str(threshold_value)

    alert_url = get_workspace_url() + '/sql/alerts/' + alert.id
    payload = json.dumps(card_payload).replace('{message_title}', message_title or alert.display_name) \
        .replace('{{QUERY_RESULT_TABLE}}', '') \
        .replace('{alert_url}', alert_url) \
        .replace('{alert_result}', alert_result) \
        .replace('{condition_text}', condition_text)
    return payload


# COMMAND ----------

from datetime import datetime
from dataclasses import dataclass, field
import requests

from pyspark.sql import DataFrame
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import sql


def send_teams_notification(alert: sql.Alert, df: DataFrame, workflow_url: str) -> requests.Response:
    """
    Sends a notification to a Microsoft Teams channel via a workflow.

    Args:
        alert (sql.Alert): The alert object containing relevant details about the alert.
        df (DataFrame): The DataFrame containing the query results to be included in the notification.
        workflow_url (str): The URL of the Teams workflow to send the notification to.

    Returns:
        Response: The response object from the HTTP request to the Teams workflow.
    """
    # send the card payload and kick off the Teams workflow
    headers = {'Content-Type': 'application/json'}
    payload = fill_in_card_details(alert, df)
    
    response = requests.post(workflow_url, headers=headers, data=payload)
    if response.status_code == 202:
        print('Message accepted for processing')
    else:
        print(f'Failed to send message, status code: {response.status_code}, response: {response.text}')
        response.raise_for_status()
    return response


def check_alert_condition(alert: sql.Alert) ->  DataFrame | None:
    """
    Executes the query associated with the alert, evaluates the alert's condition

    Args:
        alert (sql.Alert): The alert object containing the query and condition to be checked.

    Returns:
        DataFrame | None: A DataFrame if the alert's condition is met,  otherwise None.
    """
    query = w.queries.get(id=alert.query_id)
    result = spark.sql(query.query_text)
    
    if result.count() == 0:
        # query result has no rows, fallback to empty result state
        if alert.condition.empty_result_state == sql.AlertState.TRIGGERED:
            return DataFrame()
        else:
            return
    query_value = result.first()[alert.condition.operand.column.name]
    threshold_value = get_threshold_value_from_condition(alert.condition)

    match alert.condition.op:
        case sql.AlertOperator.EQUAL:
            should_trigger = query_value == threshold_value
        case sql.AlertOperator.GREATER_THAN:
            should_trigger = query_value > threshold_value
        case sql.AlertOperator.GREATER_THAN_OR_EQUAL:
            should_trigger = query_value >= threshold_value
        case sql.AlertOperator.IS_NULL:
            should_trigger = query_value is None
        case sql.AlertOperator.LESS_THAN:
            should_trigger = query_value < threshold_value
        case sql.AlertOperator.LESS_THAN_OR_EQUAL:
            should_trigger = query_value <= threshold_value
        case sql.AlertOperandColumn.NOT_EQUAL:
            should_trigger = query_value != threshold_value

    if should_trigger:
        return result
    
# master logic
w = WorkspaceClient()
alert = w.alerts.get(id=alert_id)

if result := check_alert_condition(alert):
    send_teams_notification(alert, result, workflow_url)

