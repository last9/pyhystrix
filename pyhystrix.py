"""
Module to add extra functionality like retry, circuitbreaking
to normal requests calls.

read README.md for more info on usage.
"""

import requests
import threading
from circuit_breaker import CircuitBreaker
from config import Config, logger
from urlparse import urlparse
from urllib3 import Retry
from requests.exceptions import ConnectionError
from requests import Session
from requests.adapters import HTTPAdapter
from uuid import uuid4

STATUS_FORCELIST = "status_forcelist"
MAX_TRIES = "max_tries"
METHOD_WHITELIST = "method_whitelist"
BACKOFF_FACTOR = "backoff_factor"
TIMEOUT = "timeout"
X_REQUEST_ID = "x-request-id"
HEADERS = "headers"


class Breaker(object):
    """A singleton holding a dictionary of unique key(scheme+netloc+path) to
    a circuitbreaker object.
    """
    _breakers = {}
    _lock = threading.Lock()

    @classmethod
    def get_key(cls, raw_url):
        """creates the key(scheme+netloc+path) from url"""
        o = urlparse(raw_url)
        return "".join([o.scheme, o.netloc, o.path])

    @classmethod
    def new(cls, url):
        """Returs the breaker object. If it exists in cls._breakers, return
        else create a new breaker and save it in cls._breakers before
        returning it.
        """
        key = cls.get_key(url)

        with cls._lock:
            if cls._breakers.get(key):
                logger.info("Using existing circuit for %s", url)
                return cls._breakers[key]

            logger.info("Creating new circuit for %s", url)
            breaker = CircuitBreaker(
                allowed_fails=Config.cb_fail_threshold(),
                retry_time=Config.cb_delay(),
                retry_after=Config.cb_alive_threshold(),
                failure_exceptions=Config.retriable_exceptions())

            cls._breakers[key] = breaker
            return breaker


def get_backoff_args(kwargs, method):
    """Generate backoff arguments"""
    max_tries = kwargs.get(MAX_TRIES, None)
    args = {
        METHOD_WHITELIST: Config.method_whitelist(),
        STATUS_FORCELIST: kwargs.pop(STATUS_FORCELIST,
                                     Config.status_forcelist()),
        BACKOFF_FACTOR: kwargs.pop(BACKOFF_FACTOR,
                                   Config.backoff_factor()),
        MAX_TRIES: kwargs.pop(MAX_TRIES, Config.max_tries())
    }

    if max_tries and max_tries > 0:
        args[METHOD_WHITELIST].append(method.upper())

    args[METHOD_WHITELIST] = frozenset(args[METHOD_WHITELIST])
    return args


def get_timeouts(timeout=None):
    """Ensures that both read and connect timeout are passed in
    final patched requests call. In case any of it is missing in initial
    call by the caller, default values are added"""
    if timeout:
        return timeout
    return (Config.connect_timeout(), Config.read_timeout())


def ensure_request_id(kwargs):
    """Ensures that a unique request-id is present in the request header.
    """
    headers = kwargs.get(HEADERS, {})
    if headers.get(X_REQUEST_ID):
        return
    headers[X_REQUEST_ID] = str(uuid4())
    kwargs[HEADERS] = headers


def patch_pyhystrix(func):
    """Returns a function which takes same arguments as requests.api.request
    and integrates Retry and Circuitbreaking logic in itself before calling
    session.request for actual external api call.
    """
    def pyhystrix_wrapper(method, url, **kwargs):
        logger.info("[%s %s]" % (method, url))
        circuit = Breaker.new(url)
        if circuit.is_open:
            logger.info("OPEN circuit for %s", url)
            circuit.increment_failure_count()
            raise ConnectionError("Open Circuit")

        class CustomRetry(Retry):
            def is_exhausted(self):
                # Increment fail and then check the circuit
                circuit.mark_failure()
                if circuit.is_open:
                    return True
                return super(CustomRetry, self).is_exhausted()

        ensure_request_id(kwargs)
        kwargs[TIMEOUT] = get_timeouts(kwargs.pop(TIMEOUT, None))
        bargs = get_backoff_args(kwargs, method)
        adapter = HTTPAdapter(
            max_retries=CustomRetry(total=bargs[MAX_TRIES],
                                    connect=bargs[MAX_TRIES],
                                    read=bargs[MAX_TRIES],
                                    status=bargs[MAX_TRIES],
                                    status_forcelist=bargs[STATUS_FORCELIST],
                                    method_whitelist=bargs[METHOD_WHITELIST],
                                    backoff_factor=bargs[BACKOFF_FACTOR]))
        s = Session()
        s.mount(url, adapter)
        resp = s.request(method=method, url=url, **kwargs)
        circuit.close()
        return resp

    return pyhystrix_wrapper


def patch_requests():
    """Monkey patching requests.api.request to the wrapper function above using
    patcher. This is not the best way to solve it but for now, this enables us
    to use additional functionality like Retry and circuitbreaking etc with
    least code change at the caller side.
    """
    requests.api.request = patch_pyhystrix(requests.api.request)
    logger.info("pyhystrix added to requests")


def Init():
    """Needs to be called at initialization if the application that will
    use this library.
    """
    patch_requests()
