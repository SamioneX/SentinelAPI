#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FUNCTION_NAME="${FUNCTION_NAME:-sentinel-example-api}"
ROLE_NAME="${ROLE_NAME:-sentinel-example-api-lambda-role}"
AWS_REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-sentinel-example-api-stack}"
TEMPLATE_PATH="$ROOT_DIR/build/stack.yaml"
HANDLER_PATH="$ROOT_DIR/app/main.py"

echo "Using region: $AWS_REGION"

mkdir -p "$ROOT_DIR/build"

if [[ ! -f "$HANDLER_PATH" ]]; then
  echo "Handler file not found: $HANDLER_PATH"
  exit 1
fi

aws sts get-caller-identity --region "$AWS_REGION" >/dev/null

cat > "$TEMPLATE_PATH" <<'EOF'
AWSTemplateFormatVersion: '2010-09-09'
Description: SentinelAPI example backend (Lambda + IAM role)

Parameters:
  FunctionName:
    Type: String
  RoleName:
    Type: String

Resources:
  ExampleLambdaRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Ref RoleName
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  ExampleLambdaFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: !Ref FunctionName
      Runtime: python3.12
      Handler: index.lambda_handler
      Role: !GetAtt ExampleLambdaRole.Arn
      Timeout: 10
      MemorySize: 128
      Code:
        ZipFile: |
EOF

# Embed local handler source directly into the stack template.
awk '{ print "          " $0 }' "$HANDLER_PATH" >> "$TEMPLATE_PATH"

cat >> "$TEMPLATE_PATH" <<'EOF'

  ExampleLambdaUrl:
    Type: AWS::Lambda::Url
    Properties:
      TargetFunctionArn: !Ref ExampleLambdaFunction
      AuthType: NONE
      Cors:
        AllowOrigins:
          - "*"
        AllowMethods:
          - GET
        AllowHeaders:
          - "*"

  ExampleLambdaUrlPermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref ExampleLambdaFunction
      Action: lambda:InvokeFunctionUrl
      Principal: "*"
      FunctionUrlAuthType: NONE

  ExampleLambdaInvokePermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref ExampleLambdaFunction
      Action: lambda:InvokeFunction
      Principal: "*"
      InvokedViaFunctionUrl: true

Outputs:
  FunctionName:
    Value: !Ref ExampleLambdaFunction
  FunctionArn:
    Value: !GetAtt ExampleLambdaFunction.Arn
  RoleName:
    Value: !Ref ExampleLambdaRole
  FunctionUrl:
    Value: !GetAtt ExampleLambdaUrl.FunctionUrl
EOF

echo "Deploying CloudFormation stack: $STACK_NAME"
aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_PATH" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "FunctionName=$FUNCTION_NAME" "RoleName=$ROLE_NAME" \
  --region "$AWS_REGION" >/dev/null

FUNCTION_URL="$(
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`FunctionUrl`].OutputValue' \
    --output text
)"

echo "Lambda deployed via stack: $STACK_NAME"
echo "Function name: $FUNCTION_NAME"
echo "Function URL: $FUNCTION_URL"
