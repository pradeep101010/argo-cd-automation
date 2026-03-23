import boto3
import time
import json

def patch_nodeclass_via_ssm(instance_id, cluster_name, nodeclass_name, region):
    ssm = boto3.client("ssm", region_name=region)
    command = f"""
#!/bin/bash
# Update kubeconfig
export KUBECONFIG=/home/ubuntu/.kube/config
mkdir -p /home/ubuntu/.kube
sudo chown -R ubuntu:ubuntu /home/ubuntu/.kube
aws eks update-kubeconfig --name {cluster_name} --region {region} --kubeconfig /home/ubuntu/.kube/config
echo "[CHECK] update-kubeconfig exit code: $?"
echo "[CHECK] server: $(grep server /home/ubuntu/.kube/config)"

# Debug
echo "[DEBUG] amiSelectorTerms: $(kubectl get ec2nodeclass {nodeclass_name} -o jsonpath='{{.spec.amiSelectorTerms}}')"

# Get current AMI
CURRENT_AMI=$(kubectl get ec2nodeclass {nodeclass_name} -o jsonpath='{{.spec.amiSelectorTerms[0].id}}')
echo "[CURRENT AMI] $CURRENT_AMI"

if [ -z "$CURRENT_AMI" ]; then
    echo "[ERROR] Could not read AMI ID from EC2NodeClass"
    exit 1
fi

# Get K8s version
K8S_VERSION=$(aws eks describe-cluster \
  --name {cluster_name} \
  --region {region} \
  --query 'cluster.version' \
  --output text)
echo "[K8S VERSION] $K8S_VERSION"

# Get latest AMI
LATEST_AMI=$(aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=amazon-eks-node-al2023-x86_64-standard-${{K8S_VERSION}}-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text \
  --region {region})
echo "[LATEST AMI] $LATEST_AMI"

# Compare and patch
if [ "$CURRENT_AMI" == "$LATEST_AMI" ]; then
  echo "[STATUS] UP_TO_DATE"
else
  echo "[STATUS] UPDATE_NEEDED: $CURRENT_AMI -> $LATEST_AMI"
  kubectl patch ec2nodeclass {nodeclass_name} --type merge \
    --patch '{{"spec": {{"amiSelectorTerms": [{{"id": "'"$LATEST_AMI"'"}}]}}}}'
  echo "[STATUS] EC2NodeClass PATCHED"

  echo "[STATUS] Deleting old nodes..."
  kubectl delete nodes -l karpenter.sh/nodepool
  echo "[STATUS] Nodes deleted"
fi
"""

    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        Comment=f"Patch EC2NodeClass {nodeclass_name} in {cluster_name}"
    )

    command_id = response["Command"]["CommandId"]
    print(f"[SSM] Command sent: {command_id}")

    time.sleep(5)
    for _ in range(50):
        result = ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        status = result["Status"]
        print(f"[SSM] Status: {status}")

        if status == "Success":
            print(f"[SSM] Output:\n{result['StandardOutputContent']}")
            return {"status": "success", "output": result["StandardOutputContent"]}
        elif status in ["Failed", "Cancelled", "TimedOut"]:
            print(f"[SSM] Error:\n{result['StandardErrorContent']}")
            return {"status": "failed", "error": result["StandardErrorContent"]}

        time.sleep(10)

    raise TimeoutError("SSM command timed out")


def lambda_handler(event, context):
    region         = event.get("region", "us-east-1")
    cluster_name   = event.get("cluster_name", "modmed-poc-cluster")
    nodeclass_name = event.get("nodeclass_name", "default")
    instance_id    = event.get("ssm_instance_id", "i-064ea09d850331509")

    if not instance_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "ssm_instance_id is required"})
        }

    print(f"[START] cluster={cluster_name} nodeclass={nodeclass_name} bastion={instance_id}")

    try:
        result = patch_nodeclass_via_ssm(instance_id, cluster_name, nodeclass_name, region)
        return {
            "statusCode": 200,
            "body": json.dumps(result, indent=2)
        }
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }