.PHONY: up down logs spark-logs ps peek lag console psql kpi lake maintenance test clean

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

lake:      ## list the object store (buckets, sizes)
	docker compose run --rm --no-deps -e AWS_ACCESS_KEY_ID=$${S3_ACCESS_KEY} -e AWS_SECRET_ACCESS_KEY=$${S3_SECRET_KEY} \
	  --entrypoint aws s3-init --endpoint-url http://seaweedfs:8333 s3 ls --recursive --summarize --human-readable s3://lake | tail -3

maintenance: ## run the nightly maintenance job now (summary, retention, compaction)
	docker compose --profile ops run --rm --no-deps maintenance

test:      ## run the Spark unit tests (needs: pip install pyspark==3.5.3 pytest)
	cd spark && python -m pytest -q tests

console:   ## Redpanda web UI on http://localhost:8080
	docker compose --profile tools up -d console

psql:
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

clean:     ## stop and DELETE all data volumes (lake + checkpoints go together)
	docker compose --profile tools --profile ops down -v

reset-lake: ## delete lake + checkpoints only (keeps Postgres and Kafka), then restart
	docker compose down
	docker volume rm -f bgp-pipeline_lake-data bgp-pipeline_spark-checkpoints
	docker compose up -d
