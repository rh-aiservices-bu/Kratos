IMAGE ?= quay.io/rh-aiservices-bu/maaspal:latest
SCENARIOS_DIR ?= scenarios

.PHONY: lint test build push deploy dev clean

lint:
	ruff check harness api
	mypy harness api
	cd ui && npm run lint

test:
	pytest harness/tests api/tests
	cd ui && npm test

build:
	podman build --platform linux/amd64 -t $(IMAGE) .

push: build
	podman push $(IMAGE)

deploy:
	oc get namespace maaspal >/dev/null 2>&1 || oc new-project maaspal
	oc label namespace maaspal maas.opendatahub.io/gateway-access=true --overwrite
	oc apply -k .
	oc rollout restart deployment/maaspal -n maaspal

dev:
	@echo "Starting FastAPI dev server on :8000 and Vite dev server on :5173..."
	@cd ui && npm install --silent && npm run dev &
	uvicorn api.main:app --reload --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf ui/dist ui/node_modules .mypy_cache .ruff_cache
