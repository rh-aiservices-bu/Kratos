IMAGE ?= quay.io/rlundber/kratos:0.1
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
	oc apply -k deploy/

dev:
	@echo "Starting FastAPI dev server on :8000 and Vite dev server on :5173..."
	@cd ui && npm install --silent && npm run dev &
	uvicorn api.main:app --reload --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf ui/dist ui/node_modules .mypy_cache .ruff_cache
