# NDI Module Makefile

.PHONY: help check-readiness install-deps install-yuri test clean

help: ## Show this help message
	@echo 'NDI Module Commands:'
	@echo ''
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-readiness: ## Check if module is ready to run
	python3 check_readiness.py

check-readiness-verbose: ## Check readiness with verbose output
	python3 check_readiness.py --verbose

check-readiness-json: ## Check readiness with JSON output
	python3 check_readiness.py --json

check-readiness-fix: ## Check readiness and attempt to fix issues
	python3 check_readiness.py --fix

install-deps: install-yuri ## Install all dependencies (alias for install-yuri)

install-yuri: ## Install yuri_simple automatically
	python3 install_yuri_simple.py

install-yuri-apt: ## Install yuri_simple via apt (Ubuntu/Debian)
	python3 install_yuri_simple.py --method apt

install-yuri-brew: ## Install yuri_simple via Homebrew (macOS)
	python3 install_yuri_simple.py --method brew

install-yuri-pip: ## Install yuri_simple via pip
	python3 install_yuri_simple.py --method pip

install-yuri-source: ## Install yuri_simple from source
	python3 install_yuri_simple.py --method source

check-yuri: ## Check if yuri_simple is installed
	python3 install_yuri_simple.py --check

test: ## Test the module (placeholder)
	@echo "Testing NDI module..."
	@python3 check_readiness.py --verbose
	@echo "✅ Module tests passed"

clean: ## Clean up temporary files
	@echo "Cleaning up NDI module..."
	@rm -f *.pyc
	@rm -rf __pycache__
	@echo "✅ Cleanup completed"
