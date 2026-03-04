.PHONY: help test lint deploy teardown synth anomaly-smoke sdk-deploy sdk-deploy-full sdk-teardown sdk-teardown-full

help:
	@echo "Available targets:"
	@echo "  make lint    - Run Ruff lint in local venv"
	@echo "  make test    - Run pytest in local venv"
	@echo "  make deploy  - Deploy AWS stack (SentinelStack)"
	@echo "  make teardown - Destroy AWS stack (SentinelStack)"
	@echo "  make sdk-deploy - Deploy SDK-native foundation stack"
	@echo "  make sdk-deploy-full - Deploy SDK-native full stack (build/push image)"
	@echo "  make sdk-teardown - Destroy SDK-native foundation stack"
	@echo "  make sdk-teardown-full - Destroy SDK-native full stack"
	@echo "  make synth   - CDK synth for SentinelStack"
	@echo "  make anomaly-smoke - Run end-to-end anomaly detector smoke test"

lint:
	@if [ ! -d .venv ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && python -m pip install --upgrade pip && pip install -e '.[dev]' && ruff check src tests lambda infrastructure/cdk

test:
	@./scripts/test.sh

deploy:
	@./deploy.sh

teardown:
	@./teardown.sh

synth:
	@cd infrastructure/cdk && cdk synth SentinelStack

anomaly-smoke:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/anomaly_smoke.py --stack-name SentinelStack --region $${AWS_REGION:-us-east-1}; \
	else \
		python3 scripts/anomaly_smoke.py --stack-name SentinelStack --region $${AWS_REGION:-us-east-1}; \
	fi

sdk-deploy:
	@./sdk_impl/deploy.sh

sdk-deploy-full:
	@SDK_MODE=full ./sdk_impl/deploy.sh

sdk-teardown:
	@./sdk_impl/teardown.sh

sdk-teardown-full:
	@SDK_MODE=full ./sdk_impl/teardown.sh
