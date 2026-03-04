.PHONY: help test lint deploy teardown anomaly-smoke sdk-deploy sdk-deploy-full sdk-teardown sdk-teardown-full

help:
	@echo "Available targets:"
	@echo "  make lint    - Run Ruff lint in local venv"
	@echo "  make test    - Run pytest in local venv"
	@echo "  make deploy  - Deploy SDK full stack (SentinelSdkFull)"
	@echo "  make teardown - Destroy SDK full stack (SentinelSdkFull)"
	@echo "  make sdk-deploy - Deploy SDK-native foundation stack"
	@echo "  make sdk-deploy-full - Deploy SDK-native full stack (build/push image)"
	@echo "  make sdk-teardown - Destroy SDK-native foundation stack"
	@echo "  make sdk-teardown-full - Destroy SDK-native full stack"
	@echo "  make anomaly-smoke - Run end-to-end anomaly detector smoke test"

lint:
	@if [ ! -d .venv ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && python -m pip install --upgrade pip && pip install -e '.[dev]' && ruff check src tests lambda infrastructure

test:
	@./scripts/test.sh

deploy:
	@./deploy.sh

teardown:
	@./teardown.sh

anomaly-smoke:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/anomaly_smoke.py --stack-name SentinelSdkFull --region $${AWS_REGION:-us-east-1}; \
	else \
		python3 scripts/anomaly_smoke.py --stack-name SentinelSdkFull --region $${AWS_REGION:-us-east-1}; \
	fi

sdk-deploy:
	@python3 infrastructure/deploy.py --stack-name $${STACK_NAME:-SentinelSdkFoundation} --region $${AWS_REGION:-us-east-1}

sdk-deploy-full:
	@./deploy.sh $${STACK_NAME:-SentinelSdkFull}

sdk-teardown:
	@python3 infrastructure/teardown.py --stack-name $${STACK_NAME:-SentinelSdkFoundation} --region $${AWS_REGION:-us-east-1}

sdk-teardown-full:
	@./teardown.sh $${STACK_NAME:-SentinelSdkFull}
