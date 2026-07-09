# EvoMind — convenience targets. Run `make help` for the list.
.DEFAULT_GOAL := help
.PHONY: help up down demo-gif demo-sample demo-reset

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;33m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Start the full stack (docker compose up --build)
	docker compose up --build

down: ## Stop the stack
	docker compose down

demo-gif: ## Record the README hero GIF from the running app (needs web+api up)
	bash docs/demo/make-gif.sh

demo-sample: ## (Re)generate the deterministic sample PDF only
	python3 docs/demo/make-sample-pdf.py

demo-reset: ## Revert the README hero back to the placeholder poster
	python3 docs/demo/_wire-readme.py --reset
