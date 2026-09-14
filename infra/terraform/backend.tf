# Remote state backend.
#
# This bucket and DynamoDB table are NOT created by this Terraform config —
# that would be a chicken-and-egg problem (you need a backend to store the
# state of the resources that create the backend). Bootstrap them manually,
# once, before the first `terraform init`:
#
#   aws s3api create-bucket --bucket agentshieldbucket --region us-east-2 \
#     --create-bucket-configuration LocationConstraint=us-east-2
#   aws s3api put-bucket-versioning --bucket agentshieldbucket \
#     --versioning-configuration Status=Enabled
#   aws dynamodb create-table --table-name agentshielddynamotable --region us-east-2 \
#     --attribute-definitions AttributeName=LockID,AttributeType=S \
#     --key-schema AttributeName=LockID,KeyType=HASH \
#     --billing-mode PAY_PER_REQUEST
#
# NOTE: S3 bucket names are globally unique across ALL AWS accounts, not just
# this one. If "agentshieldbucket" is already taken by someone else, the
# create-bucket call above will fail — pick a suffixed variant (e.g.
# "agentshieldbucket-<account-id>") and update the `bucket` value below to
# match before `terraform init`.
terraform {
  backend "s3" {
    bucket         = "agentshieldbucket" # bootstrap this bucket manually first — see note above if the name is taken
    key            = "agentshield/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "agentshielddynamotable"
    encrypt        = true
  }
}
