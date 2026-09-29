.PHONY: up down logs test token demo clean urls

up:            ## build and start everything
	docker compose up -d --build
	@$(MAKE) --no-print-directory urls

down:          ## stop (data is kept in ./data)
	docker compose down

logs:          ## follow Kong's logs
	docker compose logs -f kong

test:          ## run every unit test suite (no Docker needed)
	cd services/billing-service && pip install -q -r requirements.txt && python3 -m pytest -q
	cd services/usage-ingest && npm ci --silent && npm test --silent
	cd services/dashboard && npm ci --silent && npm test --silent
	lua5.1 kong/plugins/billing-meter/spec/event_spec.lua

token:         ## print an admin JWT for curl: -H "Authorization: Bearer $$(make -s token)"
	@python3 scripts/token.py

demo:          ## seed subscribers + traffic
	./scripts/demo.sh

clean:         ## stop and DELETE all data (subscribers, keys, usage)
	docker compose down -v
	rm -rf data

urls:
	@echo "Dashboard  http://localhost:3000"
	@echo "Grafana    http://localhost:3001   (Kong billing gateway dashboard)"
	@echo "Prometheus http://localhost:9090"
	@echo "Kong proxy http://localhost:8000   Admin API http://localhost:8001"
