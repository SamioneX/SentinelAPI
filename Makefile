.PHONY: help test lint local deploy synth

help:
	@echo "Available targets:"
	@echo "  make lint    - Run Ruff lint in local venv"
	@echo "  make test    - Run pytest in local venv"
	@echo "  make local   - Start local stack"
	@echo "  make deploy  - Deploy AWS stack (SentinelStack)"
	@echo "  make synth   - CDK synth for SentinelStack"

lint:
	@if [ ! -d .venv ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && python -m pip install --upgrade pip && pip install -e '.[dev]' && ruff check src tests lambda infrastructure/cdk

test:
	@./deploy.sh test

local:
	@./deploy.sh local

deploy:
	@./deploy.sh aws

synth:
	@cd infrastructure/cdk && cdk synth SentinelStack
