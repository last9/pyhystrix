"""Constants that will be used to define default
behaviour. Can be overridden by setting env vars
"""

import os
import requests
import logging


log_levels = {
    logging.getLevelName(logging.CRITICAL): logging.CRITICAL,
    logging.getLevelName(logging.ERROR): logging.ERROR,
    logging.getLevelName(logging.WARNING): logging.WARNING,
    logging.getLevelName(logging.INFO): logging.INFO,
    logging.getLevelName(logging.DEBUG): logging.DEBUG
}

logger = logging.getLogger("pyhystrix")

level = os.environ.get("PHY_LOG")
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
        return int(os.environ.get("PHY_MAX_TRIES", 3))

    @staticmethod
    def backoff_factor():
        return float(os.environ.get("PHY_BACKOFF_FACTOR", 0.5))

    @staticmethod
    def retriable_exceptions():
        return (requests.exceptions.ConnectionError,)

    @staticmethod
    def method_whitelist():
        return ['HEAD', 'GET']

    @staticmethod
    def status_forcelist():
        return [500]

    @staticmethod
    def cb_fail_threshold():
        return int(os.environ.get("PYH_CIRCUIT_FAIL_THRESHOLD", 5))

    @staticmethod
    def cb_alive_threshold():
        return int(os.environ.get("PYH_CIRCUIT_ALIVE_THRESHOLD", 20))

    @staticmethod
    def cb_delay():
        return int(os.environ.get("PYH_CIRCUIT_DELAY", 5))
