"""Constants that will be used to define default
behaviour. Can be overridden by setting env vars
"""

import os
import requests


class Config(object):
    @property
    def connect_timeout(self):
        return int(os.environ.get("PYH_CONNECT_TIMEOUT", 5))

    @property
    def read_timeout(self):
        return int(os.environ.get("PYH_READ_TIMEOUT", 5))

    @property
    def max_tries(self):
        return int(os.environ.get("PHY_MAX_RETRIES", 3))

    @property
    def retriable_exceptions(self):
        return (requests.exceptions.ConnectionError,)

    @property
    def cb_fail_threshold(self):
        return int(os.environ.get("PYH_CB_FAIL_THRESHOLD", 5))

    @property
    def cb_alive_threshold(self):
        return int(os.environ.get("PYH_CB_ALIVE_THRESHOLD", 20))

    @property
    def cb_delay(self):
        return int(os.environ.get("PYH_CB_DELAY", 10))
