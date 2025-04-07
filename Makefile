.PHONY: lint format test
TARGET ?= nkaa
lint:
	ruff check $(TARGET)
	mypy $(TARGET)
format:
	ruff format $(TARGET)
	ruff check --fix $(TARGET)
test:
	pytest
