"""One environment contract for detector publishers and Platform consumption."""

import os


def kafka_security_options(source=None) -> dict:
    source = os.environ if source is None else source
    protocol = source.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    if protocol not in {"PLAINTEXT", "SASL_PLAINTEXT"}:
        raise ValueError("Unsupported KAFKA_SECURITY_PROTOCOL")
    if protocol == "PLAINTEXT":
        return {"security_protocol": protocol}
    username = source.get("KAFKA_SASL_USERNAME", "")
    password = source.get("KAFKA_SASL_PASSWORD", "")
    if not username or not password:
        raise ValueError("SASL Kafka requires username and password")
    if source.get("KAFKA_SASL_MECHANISM", "PLAIN") != "PLAIN":
        raise ValueError("Unsupported KAFKA_SASL_MECHANISM")
    return {
        "security_protocol": protocol, "sasl_mechanism": "PLAIN",
        "sasl_plain_username": username, "sasl_plain_password": password,
    }
