"""Event-driven processing: domain events, the transactional outbox, the Kafka relay and the consumer framework.

API change ──(same transaction)──► outbox row ──relay──► Kafka topic ──► worker (consumer group)
                                                                           │ idempotent (processed_events)
                                                                           │ 3 retries, then dead_letters + DLQ
"""
