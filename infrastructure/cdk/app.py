#!/usr/bin/env python3
import os

import aws_cdk as cdk
from sentinel_cdk.stack import SentinelStack

app = cdk.App()

stack_suffix = (app.node.try_get_context("stackSuffix") or os.getenv("STACK_SUFFIX", "")).strip()
stack_name = f"SentinelStack-{stack_suffix}" if stack_suffix else "SentinelStack"

SentinelStack(
    app,
    stack_name,
)

app.synth()
