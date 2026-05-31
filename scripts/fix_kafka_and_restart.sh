#!/bin/bash
# 修复Kafka broker ID不匹配问题并重启基础设施
#
# 原因：Kafka broker ID从1001/1002变为1003，导致所有topic分区Leader:none
# 导致：LeaderNotAvailableError、GroupCoordinatorNotAvailableError、Platform服务卡死
#
# 修复：
# 1. 删除Kafka stale data（包含旧的broker ID的topic metadata）
# 2. 用固定broker ID重启Kafka
# 3. 重建并重启Platform容器（含Kafka consumer修复）

echo "=== TrafficAnalyzer Kafka 基础设施修复 ==="

# Step 1: 停止Kafka相关容器
echo "Step 1: 停止Kafka和依赖容器..."
docker compose -f docker-compose.yaml stop kafka traffic_kafka_ui traffic_platform telegraf

# Step 2: 删除Kafka stale data
echo "Step 2: 清除Kafka stale data..."
docker rm traffic_kafka 2>/dev/null || true

# Step 3: 重新创建Kafka容器
echo "Step 3: 重新创建Kafka容器..."
docker compose -f docker-compose.yaml up -d kafka
echo "等待Kafka启动..."
sleep 15

# Step 4: 创建必要的Kafka topics
echo "Step 4: 创建Kafka topics..."
docker exec traffic_kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:29092 \
    --create --topic statistics_1 --partitions 1 --replication-factor 1 --if-not-exists
docker exec traffic_kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:29092 \
    --create --topic track_complete_1 --partitions 1 --replication-factor 1 --if-not-exists
docker exec traffic_kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:29092 \
    --create --topic conflicts_1 --partitions 1 --replication-factor 1 --if-not-exists

# Step 5: 重建Platform容器
echo "Step 5: 重建并启动Platform容器..."
docker compose -f docker-compose.yaml up -d --build platform

# Step 6: 重建Nginx容器
echo "Step 6: 重建Nginx容器..."
docker compose -f docker-compose.yaml up -d --build nginx

echo "=== 修复完成 ==="
