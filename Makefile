.PHONY: lint format test test_with_api
TARGET ?= nkaa
LEGACY_DIR ?= nkaa/legacy

lint:
	ruff check --extend-exclude $(LEGACY_DIR) $(TARGET)
	mypy --exclude "$(LEGACY_DIR)" $(TARGET)

format:
	ruff format --exclude $(LEGACY_DIR) $(TARGET)
	ruff check --fix --extend-exclude $(LEGACY_DIR) $(TARGET)

test:
	pytest --ignore=$(LEGACY_DIR)

test_with_api:
	pytest --ignore=$(LEGACY_DIR) --run-live-api
