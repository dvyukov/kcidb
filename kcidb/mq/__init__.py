"""Kernel CI report message queue"""

import json
import logging
import sys
import jsonschema
from google.cloud import pubsub
from google.api_core.exceptions import DeadlineExceeded
import kcidb_io as io
from kcidb import misc


# Module's logger
LOGGER = logging.getLogger(__name__)


class Publisher:
    """Kernel CI message queue publisher"""
    # pylint: disable=no-member

    @staticmethod
    def encode_data(io_data):
        """
        Encode JSON data, adhering to a version of I/O schema, into message
        data.

        Args:
            io_data:    JSON data to be encoded, adhering to an I/O schema
                        version.

        Returns
            The encoded message data.
        """
        assert io.schema.is_valid(io_data)
        return json.dumps(io.schema.upgrade(io_data)).encode()

    def __init__(self, project_id, topic_name):
        """
        Initialize a Kernel CI message queue publisher.

        Args:
            project_id:         ID of the Google Cloud project to which the
                                message queue belongs.
            topic_name:         Name of the message queue topic to publish to.
        """
        self.client = pubsub.PublisherClient()
        self.topic_path = self.client.topic_path(project_id, topic_name)

    def init(self):
        """
        Initialize publishing setup.
        """
        self.client.create_topic(self.topic_path)

    def cleanup(self):
        """
        Cleanup publishing setup.
        """
        self.client.delete_topic(self.topic_path)

    def publish(self, data):
        """
        Publish data to the message queue.

        Args:
            data:   The JSON data to publish to the message queue.
                    Must adhere to a version of I/O schema.
        """
        assert io.schema.is_valid(data)
        self.client.publish(self.topic_path, Publisher.encode_data(data))


class Subscriber:
    """Kernel CI message queue subscriber"""
    # pylint: disable=no-member

    @staticmethod
    def decode_data(message_data):
        """
        Decode message data to extract the JSON data adhering to the latest
        I/O schema.

        Args:
            message_data:   The message data from the message queue
                            ("data" field of pubsub.types.PubsubMessage) to be
                            decoded.

        Returns
            The decoded JSON data adhering to the latest I/O schema.
        """
        data = json.loads(message_data.decode())
        return io.schema.upgrade(data, copy=False)

    def __init__(self, project_id, topic_name, subscription_name):
        """
        Initialize a Kernel CI message queue subscriber.

        Args:
            project_id:         ID of the Google Cloud project to which the
                                message queue belongs.
            topic_name:         Name of the message queue topic to subscribe
                                to.
            subscription_name:  Name of the subscription to use.
        """
        self.client = pubsub.SubscriberClient()
        self.subscription_path = \
            self.client.subscription_path(project_id, subscription_name)
        self.topic_path = self.client.topic_path(project_id, topic_name)

    def init(self):
        """
        Initialize subscription setup.
        """
        self.client.create_subscription(self.subscription_path,
                                        self.topic_path)

    def cleanup(self):
        """
        Cleanup subscription setup.
        """
        self.client.delete_subscription(self.subscription_path)

    def pull(self, max_num, timeout=0):
        """
        Pull published data from the message queue, discarding (and logging as
        errors) invalid JSON and data not matching any of the known schema
        versions.

        Args:
            max_num:    Maximum number of data messages to pull and return.
            timeout:    Maximum time to wait for request to complete, seconds,
                        or zero for infinite timeout. Default is zero.

        Returns:
            A list of "messages" - tuples containing the data received within
            the timeout, each with two items:
            * The ID to use when acknowledging the reception of the data.
            * The JSON data from the message queue, adhering to the latest I/O
              schema.
        """
        assert isinstance(max_num, int)
        assert isinstance(timeout, (int, float))
        messages = []
        while True:
            try:
                # Setting *some* timeout, because infinite timeout doesn't
                # seem to be supported
                response = self.client.pull(self.subscription_path, max_num,
                                            timeout=(timeout or 300))
                messages = response.received_messages
            except DeadlineExceeded:
                pass
            if timeout or messages:
                break

        items = []
        for message in messages:
            try:
                items.append((message.ack_id,
                              Subscriber.decode_data(message.message.data)))
            except (json.decoder.JSONDecodeError,
                    jsonschema.exceptions.ValidationError) as err:
                LOGGER.error("%s\nDropping invalid message:\n%s",
                             misc.format_exception_stack(err),
                             message.message.data)
                self.ack(message.ack_id)
        return items

    def ack(self, ack_id):
        """
        Acknowledge reception of data.

        Args:
            ack_id: The ID received with the data to be acknowledged.
        """
        self.client.acknowledge(self.subscription_path, [ack_id])

    def nack(self, ack_id):
        """
        Signal data wasn't received.

        Args:
            ack_id: The ID received with the data to be marked not received.
        """
        self.client.modify_ack_deadline(self.subscription_path, [ack_id], 0)


def publisher_init_main():
    """Execute the kcidb-mq-publisher-init command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-publisher-init - Initialize a Kernel CI report publisher'
    parser = misc.ArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the message queue topic to create',
        required=True
    )
    args = parser.parse_args()
    publisher = Publisher(args.project, args.topic)
    publisher.init()


def publisher_cleanup_main():
    """Execute the kcidb-mq-publisher-cleanup command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-publisher-cleanup - Cleanup a Kernel CI report publisher'
    parser = misc.ArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the message queue topic to remove',
        required=True
    )
    args = parser.parse_args()
    publisher = Publisher(args.project, args.topic)
    publisher.cleanup()


def publisher_publish_main():
    """Execute the kcidb-mq-publisher-publish command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-publisher-publish - ' \
        'Publish with a Kernel CI report publisher'
    parser = misc.ArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the message queue topic to publish to',
        required=True
    )
    args = parser.parse_args()
    publisher = Publisher(args.project, args.topic)
    for data in misc.json_load_stream_fd(sys.stdin.fileno()):
        data = io.schema.upgrade(data, copy=False)
        publisher.publish(data)


def subscriber_init_main():
    """Execute the kcidb-mq-subscriber-init command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-subscriber-init - Initialize a Kernel CI report subscriber'
    parser = misc.ArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the subscription\'s message queue topic',
        required=True
    )
    parser.add_argument(
        '-s', '--subscription',
        help='Name of the subscription to create',
        required=True
    )
    args = parser.parse_args()
    subscriber = Subscriber(args.project, args.topic, args.subscription)
    subscriber.init()


def subscriber_cleanup_main():
    """Execute the kcidb-mq-subscriber-cleanup command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-subscriber-cleanup - Cleanup a Kernel CI report subscriber'
    parser = misc.ArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the subscription\'s message queue topic',
        required=True
    )
    parser.add_argument(
        '-s', '--subscription',
        help='Name of the subscription to remove',
        required=True
    )
    args = parser.parse_args()
    subscriber = Subscriber(args.project, args.topic, args.subscription)
    subscriber.cleanup()


def subscriber_pull_main():
    """Execute the kcidb-mq-subscriber-pull command-line tool"""
    sys.excepthook = misc.log_and_print_excepthook
    description = \
        'kcidb-mq-subscriber-pull - Pull with a Kernel CI report subscriber'
    parser = misc.OutputArgumentParser(description=description)
    parser.add_argument(
        '-p', '--project',
        help='ID of the Google Cloud project with the message queue',
        required=True
    )
    parser.add_argument(
        '-t', '--topic',
        help='Name of the subscription\'s message queue topic',
        required=True
    )
    parser.add_argument(
        '-s', '--subscription',
        help='Name of the subscription to pull from',
        required=True
    )
    parser.add_argument(
        '--timeout',
        metavar="SECONDS",
        type=float,
        help='Wait the specified number of SECONDS for a report message, '
             'or forever, if zero',
        default=0,
        required=False
    )
    args = parser.parse_args()
    subscriber = Subscriber(args.project, args.topic, args.subscription)
    items = subscriber.pull(1, timeout=args.timeout)
    if items:
        ack_id, data = items[0]
        misc.json_dump(data, sys.stdout, indent=args.indent, seq=args.seq)
        sys.stdout.flush()
        subscriber.ack(ack_id)
