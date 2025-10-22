"""
AWS Lambda function for managing the SSM-SessionManagerRunShell document configuration.

This module provides functionality to reset the SSM Session Manager to default settings
by updating the SSM-SessionManagerRunShell document.
It's designed to be used as a CloudFormation custom resource to manage this
configuration during stack creation, updates, and deletion.
"""

import json
from time import sleep
import boto3
from botocore.config import Config
import cfnresponse
from aws_lambda_powertools import Logger

logger = Logger(service="Session Manager preferences", level="INFO")
boto3_config = Config(retries={"mode": "standard", "max_attempts": 10})

ssm = boto3.client("ssm", config=boto3_config)


def str_to_bool(value):
    """Convert a string representation of a boolean to an actual boolean."""
    if isinstance(value, bool):
        return value
    if not value:  # Empty string, None, etc.
        return False
    return value.lower() in ("true", "yes", "y", "1", "on")


def deep_compare_json(doc1, doc2):
    """
    Performs a deep comparison of two JSON documents, ignoring order and handling missing keys.

    Parameters:
        doc1 (dict): First JSON document
        doc2 (dict): Second JSON document

    Returns:
        bool: True if documents are functionally equivalent, False otherwise
    """
    # Handle different types
    if type(doc1) != type(doc2):
        return False

    # Handle dictionaries - the main case we care about
    if isinstance(doc1, dict):
        # Check if all keys in doc1 exist in doc2 with same values
        for key in doc1:
            if key not in doc2:
                return False
            if not deep_compare_json(doc1[key], doc2[key]):
                return False

        # Check if doc2 has any keys not in doc1
        for key in doc2:
            if key not in doc1:
                return False

        return True

    # Handle lists - order doesn't matter for our comparison
    elif isinstance(doc1, list):
        if len(doc1) != len(doc2):
            return False

        # For our specific use case with SSM documents, we can simplify by checking
        # if each item in doc1 has a match in doc2
        for item1 in doc1:
            found = False
            for item2 in doc2:
                if deep_compare_json(item1, item2):
                    found = True
                    break
            if not found:
                return False

        return True

    # Handle primitive types
    else:
        return doc1 == doc2


def update_ssm_document(event, document_name, operation):
    """
    Updates the specified SSM document to default settings.

    Parameters:
        document_name (str): The name of the SSM document to update

    Returns:
        dict: Response data containing message and document version

    Raises:
        Exception: Any exceptions during SSM document operations
    """
    try:
        if operation == "delete":
            updated_content = {
                "schemaVersion": "1.0",
                "description": "Document to hold regional settings for Session Manager",
                "sessionType": "Standard_Stream",
                "inputs": {
                    "s3BucketName": "",
                    "s3KeyPrefix": "",
                    "s3EncryptionEnabled": False,
                    "cloudWatchLogGroupName": "",
                    "cloudWatchEncryptionEnabled": False,
                    "cloudWatchStreamingEnabled": False,
                    "kmsKeyId": "",
                    "runAsEnabled": False,
                    "runAsDefaultUser": "",
                    "idleSessionTimeout": "20",
                },
            }
        else:
            # Get session manager preferences
            s3_logging = event["ResourceProperties"].get("S3_LOGGING", "")
            s3_bucket_name = event["ResourceProperties"].get("S3_BUCKET_NAME", "")
            s3_key_prefix = event["ResourceProperties"].get("S3_KEY_PREFIX", "")
            s3_encryption_enabled = event["ResourceProperties"].get(
                "S3_ENCRYPTION_ENABLED", ""
            )
            cw_log_group_name = event["ResourceProperties"].get("CW_LOG_GROUP_NAME", "")
            cw_encryption_enabled = event["ResourceProperties"].get(
                "CW_ENCRYPTION_ENABLED", ""
            )
            cw_streaming_enabled = event["ResourceProperties"].get(
                "CW_STREAMING_ENABLED", ""
            )
            session_data_encryption = event["ResourceProperties"].get(
                "SESSION_DATA_ENCRYPTION", ""
            )
            run_as_enabled = event["ResourceProperties"].get("RUN_AS_ENABLED", "")
            run_as_default_user = event["ResourceProperties"].get(
                "RUN_AS_DEFAULT_USER", ""
            )
            idle_session_timeout = event["ResourceProperties"].get(
                "IDLE_SESSION_TIMEOUT", ""
            )
            max_session_duration = event["ResourceProperties"].get(
                "MAX_SESSION_DURATION", ""
            )
            windows_shell_profile = event["ResourceProperties"].get(
                "WIN_SHELL_PROFILE", ""
            )
            linux_shell_profile = event["ResourceProperties"].get(
                "LINUX_SHELL_PROFILE", ""
            )
            account_id = event["ResourceProperties"].get("ACCOUNT_ID", "")
            region = event["ResourceProperties"].get("REGION", "")

            if not str_to_bool(session_data_encryption):
                session_data_key_id = ""

            if not str_to_bool(s3_logging):
                s3_bucket_name = ""
                s3_key_prefix_formatted = ""
                s3_encryption_enabled = "False"
            else:
                s3_key_prefix_formatted = ""
                if s3_key_prefix and account_id and region:
                    s3_key_prefix_formatted = f"{s3_key_prefix}/{account_id}/{region}"
                elif account_id and region:
                    s3_key_prefix_formatted = f"{account_id}/{region}"

            session_data_key_id = ""
            if str_to_bool(session_data_encryption):
                attempt = 1
                max_attempts = 12
                while attempt <= max_attempts:
                    try:
                        key_id_parameter = ssm.get_parameter(
                            Name="/session-manager/session-data-key",
                        )
                        session_data_key_id = key_id_parameter["Parameter"]["Value"]
                        logger.info("Successfully retrieved session data key.")
                        break
                    except ssm.exceptions.ParameterNotFound:
                        logger.info(
                            "Attempt #%s/%s: No session data key found. Waiting 5 seconds for the resource to be deployed.",
                            attempt,
                            max_attempts,
                        )
                        if attempt >= max_attempts:
                            logger.info(
                                "Max attempts reached. Skipping session data encryption."
                            )
                            session_data_encryption = "False"
                            break
                        attempt += 1
                        sleep(5)

            # Define the desired configuration
            updated_content = {
                "schemaVersion": "1.0",
                "description": "Document to hold regional settings for Session Manager",
                "sessionType": "Standard_Stream",
                "inputs": {
                    "s3BucketName": s3_bucket_name,
                    "s3KeyPrefix": s3_key_prefix_formatted,
                    "s3EncryptionEnabled": str_to_bool(s3_encryption_enabled),
                    "cloudWatchLogGroupName": cw_log_group_name,
                    "cloudWatchEncryptionEnabled": str_to_bool(cw_encryption_enabled),
                    "cloudWatchStreamingEnabled": str_to_bool(cw_streaming_enabled),
                    "kmsKeyId": session_data_key_id,
                    "runAsEnabled": str_to_bool(run_as_enabled),
                    "runAsDefaultUser": run_as_default_user,
                    "idleSessionTimeout": idle_session_timeout,
                    "maxSessionDuration": max_session_duration,
                },
            }

            if windows_shell_profile or linux_shell_profile:
                updated_content["inputs"]["shellProfile"] = {}
                if windows_shell_profile:
                    updated_content["inputs"]["shellProfile"][
                        "windows"
                    ] = windows_shell_profile
                if linux_shell_profile:
                    updated_content["inputs"]["shellProfile"][
                        "linux"
                    ] = linux_shell_profile

        # Check to see if the default document exists
        try:
            ssm.get_document(Name=document_name)
        except ssm.exceptions.InvalidDocument:
            # If the document doesn't exist, create it
            ssm.create_document(
                Name=document_name,
                Content=json.dumps(updated_content),
                DocumentType="Session",
                DocumentFormat="JSON",
            )
            logger.info(f"Document {document_name} created successfully")
            return {
                "Message": "Document created successfully",
                "DocumentVersion": "1",
            }

        # Get the latest version of the document
        response = ssm.get_document(Name=document_name, DocumentVersion="$LATEST")
        current_content = json.loads(response["Content"])

        # Compare current content with desired content using deep comparison
        if deep_compare_json(current_content, updated_content):
            logger.info(
                "Document already has the desired configuration. No update needed."
            )
            return {
                "Message": "Document already has the desired configuration",
                "DocumentVersion": response["DocumentVersion"],
            }

        # Update the document with new content
        try:
            update_response = ssm.update_document(
                Name=document_name,
                Content=json.dumps(updated_content),
                DocumentVersion="$LATEST",
            )

            new_version = update_response["DocumentDescription"]["DocumentVersion"]

            # Set the new version as the default
            ssm.update_document_default_version(
                Name=document_name, DocumentVersion=new_version
            )

            logger.info(f"Document updated successfully to version {new_version}")
            return {
                "Message": "Document updated successfully",
                "DocumentVersion": new_version,
            }

        except ssm.exceptions.DuplicateDocumentContentException:
            # This exception occurs when the document content is identical
            logger.info("Document content is identical. No update needed.")
            return {
                "Message": "Document already has the desired configuration",
                "DocumentVersion": response["DocumentVersion"],
            }

    except ssm.exceptions.InvalidDocument:
        logger.error(f"Invalid document: {document_name}")
        raise
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        raise


def lambda_handler(event, context):
    """
    AWS Lambda function handler that processes CloudFormation custom resource events.

    This function updates the SSM-SessionManagerRunShell document to default settings
    during Create/Update events.

    Parameters:
        event (dict): The event dict containing details about the CloudFormation request
                    including RequestType (Create, Update, Delete)
        context (object): Lambda context runtime information

    Returns:
        dict: Response containing status code and completion message
    """
    logger.info("Received event: %s", event)

    # Setting physical resource ID to stack ID
    physical_resource_id = event["ResourceProperties"].get(
        "STACK_NAME", "session-manager"
    )

    # Skip processing if this is not a Create or Update request
    if event["RequestType"] not in ["Create", "Update", "Delete"]:
        cfnresponse.send(
            event=event,
            context=context,
            responseStatus=cfnresponse.SUCCESS,
            responseData={"Message": f'Nothing to do for {event["RequestType"]}'},
            physicalResourceId=physical_resource_id,
        )
        return

    try:
        document_name = "SSM-SessionManagerRunShell"

        if event["RequestType"] in ["Create", "Update"]:
            response_data = update_ssm_document(
                event=event, document_name=document_name, operation="update"
            )
            cfnresponse.send(
                event=event,
                context=context,
                responseStatus=cfnresponse.SUCCESS,
                responseData=response_data,
                physicalResourceId=physical_resource_id,
            )
        else:
            response_data = update_ssm_document(
                event=event, document_name=document_name, operation="delete"
            )
            cfnresponse.send(
                event=event,
                context=context,
                responseStatus=cfnresponse.SUCCESS,
                responseData=response_data,
                physicalResourceId=physical_resource_id,
            )

    except Exception as e:
        error_message = f"Error updating document: {str(e)}"
        logger.error(error_message)
        cfnresponse.send(
            event=event,
            context=context,
            responseData={"Error": error_message},
            responseStatus=cfnresponse.FAILED,
            physicalResourceId=physical_resource_id,
        )

    return {"statusCode": 200, "body": json.dumps("Complete")}
