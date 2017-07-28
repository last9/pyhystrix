"""Constants that will be used to define default
behaviour. Can be overridden by setting env vars
"""

import os
import requests
import logging


log_levels = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG
}

logger = logging.getLogger("pyhystrix")

level = os.environ.get("PHY_LOG", "WARNING")
logger.setLevel(log_levels.get(level, logging.WARNING))
logger.addHandler(logging.StreamHandler())



class Config(object):
    @staticmethod
    def connect_timeout():
        return int(os.environ.get("PYH_CONNECT_TIMEOUT", 5))

    @staticmethod
    def read_timeout():
        return int(os.environ.get("PYH_READ_TIMEOUT", 5))

    @staticmethod
    def max_tries():
        return int(os.environ.get("PHY_MAX_RETRIES", 3))

    @staticmethod
    def retriable_exceptions():
        return (requests.exceptions.ConnectionError,)

    @staticmethod
    def cb_fail_threshold():
        return int(os.environ.get("PYH_CIRCUIT_FAIL_THRESHOLD", 5))

    @staticmethod
    def cb_alive_threshold():
        return int(os.environ.get("PYH_CIRCUIT_ALIVE_THRESHOLD", 20))

    @staticmethod
    def cb_delay():
        return int(os.environ.get("PYH_CIRCUIT_DELAY", 5))
