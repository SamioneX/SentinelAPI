.PHONY: help test lint local deploy-cost deploy-prod synth-cost synth-prod

help:
	@echo "Available targets:"
	@echo "  make lint         - Run Ruff lint in local venv"
	@echo "  make test         - Run pytest in local venv (cost-optimized profile)"
	@echo "  make local        - Start local stack (cost-optimized profile)"
	@echo "  make deploy-cost  - Deploy AWS cost-optimized stack"
	@echo "  make deploy-prod  - Deploy AWS production-grade stack"
	@echo "  make synth-cost   - CDK synth for cost-optimized"
	@echo "  make synth-prod   - CDK synth for production-grade"

lint:
	@if [ ! -d .venv ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && python -m pip install --upgrade pip && pip install -e '.[dev]' && ruff check src tests lambda infrastructure/cdk

test:
	@./deploy.sh test cost-optimized

local:
	@./deploy.sh local cost-optimized

deploy-cost:
	@./deploy.sh aws cost-optimized

deploy-prod:
	@./deploy.sh aws production-grade

synth-cost:
	@cd infrastructure/cdk && cdk synth SentinelStack-cost -c deploymentProfile=cost-optimized -c stackSuffix=cost

synth-prod:
	@cd infrastructure/cdk && cdk synth SentinelStack-prod -c deploymentProfile=production-grade -c stackSuffix=prod
