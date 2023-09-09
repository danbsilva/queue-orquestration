import json
import os
from time import sleep

from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError


class KafkaService:

    default_config = {
        'bootstrap_servers': os.getenv('KAFKA_SERVER'),
    }

    config_producer = {
        'value_serializer': lambda v: json.dumps(v).encode('utf-8')
    }

    config_consumer = {
        'group_id': 'logs_service_group',
        'auto_offset_reset': 'earliest'
    }

    def is_broker_available(self):
        try:
            config = {**self.default_config}
            consumer = KafkaConsumer(**config)
            return True
        except KafkaError:
            return False


    def wait_for_broker(self):
        while not self.is_broker_available():
            sleep(1)


    def consumer(self, app, topic, callback):
        self.wait_for_broker()
        try:
            config = {**self.default_config, **self.config_consumer}
            kafka_consumer = KafkaConsumer(**config)

            kafka_consumer.subscribe([topic])

            for message in kafka_consumer:
                kafka_consumer.poll(0.5)
                key = message.key.decode('utf-8')
                msg = json.loads(message.value.decode('utf-8'))
                callback(app, key, msg)

        except KafkaError as e:
            print(f'Erro ao enviar a mensagem: {str(e)}')


    def producer(self, topic, key, value):
        try:
            config = {**self.default_config, **self.config_producer}
            kafka_producer = KafkaProducer(**config)
            kafka_producer.send(topic, key=key.encode('utf-8'), value=value)
            kafka_producer.flush()
            kafka_producer.close()
        except KafkaError as e:
            print(f'Erro ao enviar a mensagem: {str(e)}')