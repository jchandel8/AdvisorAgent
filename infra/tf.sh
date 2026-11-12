#!/usr/bin/env sh
# Run Terraform from its Docker image (nothing to install), using your AWS CLI login (~/.aws, read-only).
#   infra/tf.sh persistent init
#   infra/tf.sh persistent plan        # read-only: shows what would change
#   infra/tf.sh persistent apply       # creates/changes AWS resources (asks before doing it)
set -eu
STACK="$1"; shift
HERE="$(cd "$(dirname "$0")" && pwd)"
exec docker run --rm -it \
  -v "$HERE":/infra \
  -v "$HOME/.aws":/root/.aws:ro \
  -e AWS_PROFILE -e AWS_REGION="${AWS_REGION:-us-west-1}" \
  -w "/infra/$STACK" \
  hashicorp/terraform:1.17.2 "$@"
