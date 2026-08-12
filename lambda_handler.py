"""
Entry point for the AWS Lambda that EventBridge Scheduler invokes every 4 hours.

Deployment note: package this file + app/ + dependencies as a Lambda deployment package
(or container image), set DATABASE_URL / AWS_REGION / etc. as Lambda environment variables,
and create an EventBridge Scheduler rule with a `rate(4 hours)` expression targeting it.
"""

from app.ingest import run_ingest


def handler(event, context):
    result = run_ingest()
    return {"statusCode": 200, "body": result}
