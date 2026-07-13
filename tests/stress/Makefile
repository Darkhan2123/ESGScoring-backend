# ---------------------------------------------------------------------------
# k6 stress test convenience targets
# ---------------------------------------------------------------------------
# Usage:
#   cd tests/stress && make stress-smoke         # Run smoke test
#   cd tests/stress && make stress-load          # Run load test
#   cd tests/stress && make stress-setup         # Generate test users
#   make -C tests/stress stress-smoke            # Same from project root
# ---------------------------------------------------------------------------

BASE_URL ?= http://localhost
REPORTS_DIR ?= reports

reports:
	mkdir -p $(REPORTS_DIR)

# Generate tokens on the host (not inside Docker) so k6 can read the file.
stress-setup:
	cd ../.. && python manage.py generate_stress_users --count 15

stress-smoke: reports
	k6 run smoke-test.js \
		-e BASE_URL=$(BASE_URL)

stress-load: reports
	k6 run load-test.js \
		-e BASE_URL=$(BASE_URL) \
		--out html=$(REPORTS_DIR)/load-test-$$(date +%s).html

stress-load-json: reports
	k6 run load-test.js \
		-e BASE_URL=$(BASE_URL) \
		--out json=$(REPORTS_DIR)/load-test-$$(date +%s).json

stress-load-csv: reports
	k6 run load-test.js \
		-e BASE_URL=$(BASE_URL) \
		--out csv=$(REPORTS_DIR)/load-test-$$(date +%s).csv

.PHONY: reports stress-setup stress-smoke stress-load stress-load-json stress-load-csv
