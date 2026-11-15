.PHONY: backup setup health prod-up up down logs spark-logs ps peek lag console psql kpi lake maintenance test clean

setup:     ## create .env with random secrets (first time only)
	./scripts/setup.sh

health:    ## is everything running and is the data fresh?
	@docker compose ps --format 'table {{.Service}}\t{{.Status}}'
	@curl -s http://localhost:3000/health || echo 'website/API not answering yet'; echo

prod-up:   ## production: only the website is public (set SITE_ADDRESS in .env)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

up:        ## build and start everything, then open http://localhost:3000
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

lake:      ## object store totals per layer (credentials come from the service's .env settings)
	@for p in bronze silver gold; do \
	  printf '%-8s' $$p; \
	  docker compose run --rm --no-deps --entrypoint aws s3-init --endpoint-url http://seaweedfs:8333 \
	    s3 ls --recursive --summarize --human-readable s3://lake/$$p/ 2>/dev/null | grep -E 'Total (Objects|Size)' | tr '\n' ' '; echo; \
	done

maintenance: ## run maintenance now inside the running Spark job (watch: make spark-logs)
	docker compose exec spark touch /data/checkpoints/run-maintenance

test:      ## run the Spark unit tests (needs: pip install pyspark==3.5.3 pytest)
	cd spark && python -m pytest -q tests

console:   ## Redpanda web UI on http://localhost:8080
	docker compose --profile tools up -d console

psql:
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

clean:     ## stop and DELETE all data volumes (lake + checkpoints go together)
	docker compose --profile tools down -v

reset-lake: ## delete lake + checkpoints only (keeps Postgres and Kafka), then restart
	docker compose down
	docker volume rm -f bgp-pipeline_lake-data bgp-pipeline_spark-checkpoints
	docker compose up -d

backup:    ## save the database (KPIs, events, names) to backups/ as a compressed file
	@mkdir -p backups
	docker compose exec -T postgres sh -c 'pg_dump -U "$$POSTGRES_USER" "$$POSTGRES_DB"' | gzip > backups/bgp-$$(date +%Y%m%d-%H%M).sql.gz
	@ls -lh backups | tail -1
