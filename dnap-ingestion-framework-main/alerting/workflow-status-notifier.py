# Databricks notebook source
# MAGIC %md
# MAGIC ## Adding Microsoft Teams alerting to a Databricks workflow
# MAGIC
# MAGIC Databricks has built-in Teams webhook notifications when a job succeeds or fails. However, Microsoft has [deprecated webhooks](https://answers.microsoft.com/en-us/msteams/forum/all/microsoft-365-connectors-deprecation/b63e017e-0816-4fd9-9a3a-e3f54abe8984) through Office 365 connectors. They recommend using a Power Automate workflow instead.
# MAGIC
# MAGIC ### Setting up the Teams workflow
# MAGIC
# MAGIC In the Teams app or web client, open the channel you wish to receive the status updates about the job. From more options -> Workflows, choose “Post to a chat when a webhook request is received”. After creating the workflow, copy the webhook url used to trigger it (this will be used later as the teams_webhook_url). You can view the workflow in Teams later and review the steps. The default steps to send each adaptive card will work fine.
# MAGIC
# MAGIC ![Create Workflow](../documentation/create-workflow.png)
# MAGIC
# MAGIC ### Triggering the workflow from your Databricks job
# MAGIC
# MAGIC You can use this notebook that accepts a job run id from Databricks, uses the databricks python sdk to get the current status of the job, then sends a request to start the workflow on Teams. The AdaptiveCard json built by the notebook will contain the name of the job, the Spark catalog it is running in, the Run Duration of the job, and the name and status of each task (except the ones that contain the string “notify_teams” since they are not part of the real work). Here is an example of what it could look like.
# MAGIC
# MAGIC ![Example Card](../documentation/example-card.png)
# MAGIC
# MAGIC Call the notebook from anywhere in the execution path of your job when you want to alert. If you want to alert exactly once at the end of the job, you can create a single task that is dependent on all other tasks. Set it to run “if all done”. See below for a basic example: 
# MAGIC
# MAGIC ![Example Workflow](../documentation/example-workflow.png)
# MAGIC
# MAGIC To add the alerting task, just add a task that calls the notebook linked above. The notebook that sends the alert is configured so that only the tasks with a key that does NOT contain “notify_teams” will be alerted on. For this reason, be sure to add that string to the task name, otherwise it will show up itself in the alert.
# MAGIC For the parameters for the job, set up these 3:
# MAGIC
# MAGIC `run_id`:	{{job.run_id}}
# MAGIC
# MAGIC `teams_webhook_url`:	(the webhook url you copied from part 1)
# MAGIC
# MAGIC `teams_error_webhook_url`: (another webhook url you can set up like part 1)
# MAGIC
# MAGIC The error webhook url is optional. The channel associated with this webhook will receive messages only when an error happens. We have found it useful in cases where team members only want to be alerted on an error condition.
# MAGIC For the run_id, you can use the double {{ }} syntax to have Databricks automatically populate it at runtime.
# MAGIC
# MAGIC ![Example Task](../documentation/example-task.png)
# MAGIC

# COMMAND ----------

# DBTITLE 1,Helper Functions
import requests
import json
from datetime import datetime

from databricks.sdk.service.jobs import Run, RunTask, RunResultState


def format_duration(milliseconds: int):
    seconds = (milliseconds // 1000) % 60
    minutes = (milliseconds // (1000 * 60)) % 60
    hours = (milliseconds // (1000 * 60 * 60)) % 24

    if hours > 0:
        return f'{hours}:{minutes:02}:{seconds:02}'
    elif minutes > 0:
        return f'{minutes:02}:{seconds:02}'
    else:
        return f'00:{seconds:02}'
    

def get_table_row(task: RunTask):
    if 'notify_teams' in task.task_key:
        # we dont need to show the task that is running this job
        return

    status = task.state.result_state
    table_row = {
        "type": "TableRow",
        "cells": [
            {
                "type": "TableCell",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": task.task_key,
                        "wrap": True
                    }
                ],
                "verticalContentAlignment": "Center"
            },
            {
                "type": "TableCell",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": status.value if status else '',
                        "wrap": True,
                        "color": get_status_color(status),
                        "horizontalAlignment": "Right"
                    }
                ]
            }
        ]
    }
    return table_row


def get_status_color(status: RunResultState):   
    color_map = {
        RunResultState.CANCELED: 'Warning',
        RunResultState.EXCLUDED: 'Default',
        RunResultState.FAILED: 'Attention',
        RunResultState.MAXIMUM_CONCURRENT_RUNS_REACHED: 'Attention',
        RunResultState.SUCCESS: 'Good',
        RunResultState.SUCCESS_WITH_FAILURES: 'Warning',
        RunResultState.TIMEDOUT: 'Attention',
        RunResultState.UPSTREAM_CANCELED: 'Default',
        RunResultState.UPSTREAM_FAILED: 'Default',
    }
    return color_map.get(status, 'Default')


def run_has_errors(run: Run):
    error_states = [RunResultState.FAILED, RunResultState.MAXIMUM_CONCURRENT_RUNS_REACHED, RunResultState.TIMEDOUT]
    for task in run.tasks:
        if task.state.result_state in error_states:
            return True
    return False
    

def send_teams_notification(run: Run):
    # add tasks to initial card payload
    run.tasks.sort(key=lambda x: x.end_time or int(datetime.max.timestamp()))
    table_rows = card_payload['attachments'][0]['content']['body'][2]['rows']
    for task in run.tasks:
        if table_row := get_table_row(task):
            table_rows.append(table_row)

    # send the card payload and kick off the Teams workflow
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps(card_payload)
    
    response = requests.post(webhook_url, headers=headers, data=payload)
    if error_webhook_url and run_has_errors(run):
        response = requests.post(error_webhook_url, headers=headers, data=payload)
    return response


# COMMAND ----------

# DBTITLE 1,Send notification for the given runId
from databricks.sdk import WorkspaceClient

dbutils.widgets.text('run_id', '')
run_id = dbutils.widgets.get('run_id')
webhook_url = dbutils.widgets.get('teams_webhook_url')
error_webhook_url = dbutils.widgets.get('teams_error_webhook_url')

if not webhook_url:
    raise Exception('Please set the webhook URL as a job parameter (teams_webhook_url)')
if not run_id:
    raise Exception('Please set the runId as a notebook parameter (runId)')

w = WorkspaceClient()
run = w.jobs.get_run(run_id=run_id)
run_duration = format_duration(run.run_duration)

current_catalog = spark.catalog.currentCatalog()

# build initial card
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
                                                "text": run.run_name,
                                                "wrap": True,
                                                "style": "heading"
                                            }
                                        ],
                                        "width": 70,
                                        "horizontalAlignment": "Left",
                                        "selectAction": {
                                            "type": "Action.OpenUrl",
                                            "url": run.run_page_url
                                        }
                                    },
                                    {
                                        "type": "Column",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": current_catalog,
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
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {
                                "title": "Run Duration",
                                "value": run_duration
                            }
                        ],
                        "spacing": "Large",
                    },
                    {
                        "type": "Table",
                        "columns": [
                            {
                                "width": 2
                            },
                            {
                                "width": 1
                            }
                        ],
                        "rows": [],
                        "spacing": "ExtraLarge",
                        "firstRowAsHeaders": False,
                        "verticalCellContentAlignment": "Center",
                        "showGridLines": False,
                        "separator": True
                    }
                ]
            }
        }
    ]
}

response = send_teams_notification(run)

if response.status_code == 202:
    print('Message accepted for processing')
else:
    print(f'Failed to send message, status code: {response.status_code}, response: {response.text}')

