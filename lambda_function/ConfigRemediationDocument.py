import json
import boto3

iam_client = boto3.client("iam")
config_client = boto3.client("config")

responses = {}
responses["AttachRolePolicyResponses"] = []


def get_role_name_from_id(role_id):
    response = config_client.get_resource_config_history(
        resourceType="AWS::IAM::Role", resourceId=role_id, limit=1
    )

    config_item = response["configurationItems"][0]
    role_name = config_item.get("resourceName")
    account_id = config_item.get("accountId")

    configuration = json.loads(config_item.get("configuration"))
    attached_managed_policies = configuration.get("attachedManagedPolicies", [])
    return role_name, attached_managed_policies, account_id


def attach_policy_handler(event, context):
    try:
        # Get role ID from event
        role_id = event.get("IAMResourceId")

        # Get policy name from event
        ssm_policy_name = event.get("SSMPolicyName", "SessionManagerLogPolicy")

        # Get role name from role ID
        role_name, attached_managed_policies, account_id = get_role_name_from_id(
            role_id
        )

        # Check if policy is already attached
        policy_already_attached = False
        for policy in attached_managed_policies:
            if policy.get("policyName") == ssm_policy_name:
                policy_already_attached = True
                break

        if policy_already_attached:
            return {
                "output": f"IAM Policy {ssm_policy_name} is already attached to role {role_name}.",
                "http_response": responses,
            }

        # Attach the policy to the role (Assumes policy is in the main path)
        policy_arn = f"arn:aws:iam::{account_id}:policy/{ssm_policy_name}"
        response = iam_client.attach_role_policy(
            RoleName=role_name, PolicyArn=policy_arn
        )

        responses["AttachRolePolicyResponses"].append(
            {"RoleName": role_name, "Response": response}
        )

        # Verify the policy was attached
        verification = iam_client.list_attached_role_policies(RoleName=role_name)
        policy_attached = False

        for policy in verification.get("AttachedPolicies", []):
            if policy.get("PolicyArn") == policy_arn:
                policy_attached = True
                break

        if not policy_attached:
            error_msg = f"Failed to attach IAM Policy {policy_arn} to role {role_name}."
            raise Exception(error_msg)

        return {
            "output": f"IAM Policy {policy_arn} attached successfully to role {role_name}.",
            "http_response": responses,
        }

    except Exception as e:
        error_msg = f"Unexpected error in attach_policy_handler: {str(e)}"
        return {"output": error_msg, "http_response": responses}
