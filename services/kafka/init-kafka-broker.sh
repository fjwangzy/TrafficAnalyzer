#!/bin/sh
mkdir -p /etc/kafka && cp /kafka_server_jaas.conf /etc/kafka/ && exec start-kafka.sh