.PHONY: up down logs spark-logs ps peek lag console psql kpi clean

up:        ## build and start everything
	docker compose up -d --build

down:      ## stop (data is kept)
	docker compose down

spark-logs: ## follow the Spark job
	docker compose logs -f spark

kpi:       ## newest KPI rows in Postgres
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "select window_start, announcements, withdrawals, total_updates from kpi_events_1m order by window_start desc limit 5;"'

logs:      ## follow the producer
	docker compose logs -f producer

ps:
	docker compose ps

peek:      ## print 3 messages from the topic
	docker compose exec redpanda rpk topic consume $${KAFKA_TOPIC:-ris.updates.raw} -n 3

lag:       ## topic size and partitions
	docker compose exec redpanda rpk topic describe $${KAFKA_TOPIC:-ris.updates.raw} -p

console:   ## Redpanda web UI on http://localhost:8080
	docker compose --profile tools up -d console

psql:
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

clean:     ## stop and DELETE all data volumes
	docker compose --profile tools down -v
