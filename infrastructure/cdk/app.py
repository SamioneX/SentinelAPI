#!/usr/bin/env python3
import os

import aws_cdk as cdk
from sentinel_cdk.stack import SentinelStack

app = cdk.App()

deployment_profile = app.node.try_get_context("deploymentProfile") or os.getenv(
    "DEPLOYMENT_PROFILE", "cost-optimized"
)
stack_suffix = app.node.try_get_context("stackSuffix") or deployment_profile.replace("-", "")

SentinelStack(
    app,
    f"SentinelStack-{stack_suffix}",
    deployment_profile=deployment_profile,
)

app.synth()
