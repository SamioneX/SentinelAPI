#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <svg-path> <asset-key>"
  echo "Example: $0 build/diagrams/arch-diagram.svg sentinelapi/diagrams/arch-diagram.svg"
  exit 1
fi

SVG_PATH="$1"
ASSET_KEY="$2"
ASSET_BUCKET_TAG="${ASSET_BUCKET_TAG:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ -z "$ASSET_BUCKET_TAG" ]]; then
  echo "ASSET_BUCKET_TAG is required (format: key=value)"
  exit 1
fi

if [[ ! -f "$SVG_PATH" ]]; then
  echo "SVG not found: $SVG_PATH"
  exit 1
fi

TAG_KEY="${ASSET_BUCKET_TAG%%=*}"
TAG_VALUE="${ASSET_BUCKET_TAG#*=}"

if [[ -z "$TAG_KEY" || -z "$TAG_VALUE" || "$TAG_KEY" == "$ASSET_BUCKET_TAG" ]]; then
  echo "Invalid ASSET_BUCKET_TAG. Expected format key=value, got: $ASSET_BUCKET_TAG"
  exit 1
fi

resolve_bucket_by_rgta() {
  aws resourcegroupstaggingapi get-resources \
    --region "$AWS_REGION" \
    --resource-type-filters s3 \
    --tag-filters "Key=${TAG_KEY},Values=${TAG_VALUE}" \
    --query 'ResourceTagMappingList[0].ResourceARN' \
    --output text 2>/dev/null | sed -E 's#^arn:aws:s3:::(.+)$#\1#'
}

resolve_bucket_by_scan() {
  local candidate
  while IFS= read -r candidate; do
    if aws s3api get-bucket-tagging --bucket "$candidate" \
      --query "TagSet[?Key=='${TAG_KEY}' && Value=='${TAG_VALUE}'] | length(@)" \
      --output text >/dev/null 2>&1; then
      local match_count
      match_count="$(aws s3api get-bucket-tagging --bucket "$candidate" \
        --query "TagSet[?Key=='${TAG_KEY}' && Value=='${TAG_VALUE}'] | length(@)" \
        --output text 2>/dev/null || echo 0)"
      if [[ "$match_count" != "0" ]]; then
        echo "$candidate"
        return 0
      fi
    fi
  done < <(aws s3api list-buckets --query 'Buckets[].Name' --output text | tr '\t' '\n')
  return 1
}

BUCKET_NAME="$(resolve_bucket_by_rgta || true)"
if [[ -z "$BUCKET_NAME" || "$BUCKET_NAME" == "None" ]]; then
  BUCKET_NAME="$(resolve_bucket_by_scan || true)"
fi

if [[ -z "$BUCKET_NAME" || "$BUCKET_NAME" == "None" ]]; then
  echo "No S3 bucket found for tag ${TAG_KEY}=${TAG_VALUE}"
  exit 1
fi

S3_URI="s3://${BUCKET_NAME}/${ASSET_KEY}"
echo "Uploading ${SVG_PATH} to ${S3_URI}"

aws s3 cp "$SVG_PATH" "$S3_URI" \
  --region "$AWS_REGION" \
  --content-type "image/svg+xml" \
  --cache-control "public, max-age=300"

echo "Published diagram asset: ${S3_URI}"
