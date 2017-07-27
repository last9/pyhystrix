"""
Module to add extra functionality like retry, circuitbreaking
to normal requests calls.

read README.md for more info on usage.
"""

import requests
import threading
from circuit_breaker import CircuitBreaker
from config import Config
from urlparse import urlparse
from urllib3 import Retry
from requests import Session
from requests.adapters import HTTPAdapter
from uuid import uuid4

__breakers = None
CONFIG = Config()


class Breakers(object):
    """A singleton holding a dictionary of unique key(scheme+netloc+path) to
    a circuitbreaker object.
    """
    def __init__(self, config):
        """Initialize Breakers object. Apart from the map of
        circuitbreakers, each Breakers object also has a Lock.
        It is advised to take lock before any action on the object.
        """
        self._breakers = {}
        self.lock = threading.Lock()
        self.cb_fail_threshold = config.cb_fail_threshold
        self.cb_delay = config.cb_delay
        self.cb_alive_threshold = config.cb_alive_threshold
        self.retriable_exceptions = config.retriable_exceptions

    def new(self, key):
        """Returs the breaker object. If it exists in self._breakers, return
        else create a new breaker and save it in self._breakers before
        returning it.
        """
        if self._breakers.get(key):
            return self._breakers[key]

        breaker = CircuitBreaker(allowed_fails=self.cb_fail_threshold,
                                 retry_time=self.cb_delay,
                                 retry_after=self.cb_alive_threshold,
                                 failure_exceptions=self.retriable_exceptions)
        self._breakers[key] = breaker
        return breaker


def get_backoff_args(kwargs):
    return {
        "max_tries": kwargs.pop("retries", CONFIG.max_tries)
    }


def get_breaker(raw_url):
    """creates the key(scheme+netloc+path) from url and
    fetch breaker from breakers singleton"""
    o = urlparse(raw_url)
    key = "".join([o.scheme, o.netloc, o.path])
    breaker = None

    with __breakers.lock:
        breaker = __breakers.new(key)
    return breaker


def get_timeouts(timeout=None):
    """Ensures that both read and connect timeout are passed in
    final patched requests call. In case any of it is missing in initial
    call by the caller, default values are added"""
    if timeout:
        return timeout
    return (CONFIG.connect_timeout, CONFIG.read_timeout)


def ensure_request_id(kwargs):
    """Ensures that a unique request-id is present in the request header.
    """
    headers = kwargs.get("headers", {})
    if headers.get("request-id"):
        return
    headers["request-id"] = str(uuid4())
    kwargs["headers"] = headers


def patcher(func):
    """Returns a function which takes same arguments as requests.api.request
    and integrates Retry and Circuitbreaking logic in itself before calling
    session.request for actual external api call.
    """
    def wrapper(method, url, **kwargs):
        circuit = get_breaker(url)
        if circuit.is_open:
            circuit.increment_failure_count()
            return None

        class CustomRetry(Retry):
            def is_exhausted(self):
                # Increment fail and then check the circuit
                circuit.mark_failure()
                if circuit.is_open:
                    return True
                return super(CustomRetry, self).is_exhausted()

        ensure_request_id(kwargs)
        bargs = get_backoff_args(kwargs)
        kwargs["timeout"] = get_timeouts(kwargs.pop("timeout", None))

        adapter = HTTPAdapter(max_retries=CustomRetry(total=None,
                              connect=bargs["max_tries"]))
        s = Session()
        s.mount(url, adapter)
        resp = s.request(method=method, url=url, **kwargs)
        circuit.close()
        return resp

    return wrapper


def patch_requests():
    """Monkey patching requests.api.request to the wrapper function above using
    patcher. This is not the best way to solve it but for now, this enables us
    to use additional functionality like Retry and circuitbreaking etc with
    least code change at the caller side.
    """
    requests.api.request = patcher(requests.api.request)


def Init():
    """Needs to be called at initialization if the application that will
    use this library.
    """
    global __breakers
    __breakers = Breakers(CONFIG)
    patch_requests()
