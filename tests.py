from __future__ import print_function
import os
import unittest
import time
import requests
import random
import http
import logging
from io import BytesIO
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import ConnectTimeoutError
from requests.exceptions import ConnectionError, RetryError
from config import logger
from httmock import all_requests, HTTMock
from uuid import uuid4

import pyhystrix
import circuit_breaker
from pyhystrix import Config

DEFAULT_FAILS = 3
DEFAULT_RETRY = 1
DEFAULT_OPEN_CIRCUIT_THREASHOLD = 5


def validation_stub(number):
    return number > 0


def raises_something(exc):
    raise exc


def new_url():
    return "http://www.%s.com" % str(uuid4())


HTTP_RESPONSE_STR = u"""HTTP/1.1 %s
Date: Thu, Jul  3 15:27:54 2014
Content-Type: text/xml; charset="utf-8"
Connection: close
Content-Length: 626"""


class CustomLogHandler(logging.StreamHandler):
    def __init__(self):
        self.emit_count = 0
        super(CustomLogHandler, self).__init__()

    def emit(self, record):
        self.emit_count += 1
        super(CustomLogHandler, self).emit(record)


class CustomFailureMock(object):
    """patching _new_conn method of HTTPConnection
    to mock real external http call.
    """
    def __init__(self, func):
        self._func = func

    def __enter__(self):
        self._real_func = HTTPConnection._new_conn
        HTTPConnection._new_conn = self._func
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        HTTPConnection._new_conn = self._real_func


class FakeHttplibSocket(object):
    """Fake `httplib.HTTPResponse` replacement."""

    def __init__(self, response_string):
        """Initialize new `FakeHttplibSocket`."""
        self._buffer = BytesIO(response_string.encode("iso-8859-1"))

    def makefile(self, _mode):
        """Returns the socket's internal buffer."""
        return self._buffer


class CustomHTTPResponseMock(object):
    """Patching urllib3.connectionpool.HTTPConnectionPool._make_request
    to simulate http call and return HTTP_RESPONSE_STR with custom status code
    and increase the try counter
    """
    def __init__(self, counter, status=200):
        self._status = status
        self._counter = counter

    def __enter__(self):
        status = self._status
        counter = self._counter

        def fake_make_request(self, conn, method, url, **kwargs):
            counter["retried"] += 1
            sock = FakeHttplibSocket(HTTP_RESPONSE_STR % status)
            resp = http.client.HTTPResponse(sock)
            resp.begin()
            return resp

        self._real_func = HTTPConnectionPool._make_request
        HTTPConnectionPool._make_request = fake_make_request
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        HTTPConnectionPool._make_request = self._real_func


class TestTimeouts(unittest.TestCase):
    def setUp(self):
        pyhystrix.Init()

    def test_default_connect_timeout(self):
        now = int(time.time())
        timeout = Config.connect_timeout()
        try:
            requests.get("http://google.com:488", max_tries=0)
        except ConnectionError:
            self.assertTrue(int(time.time()) - now >= timeout)
        else:
            raise Exception("Should have raised ConnectionError")


class TestRetry(unittest.TestCase):
    def setUp(self):
        pyhystrix.Init()

    def test_default_retry(self):
        temp = {"retried": -1}
        max_tries = Config.max_tries()

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            returnedError = None
            try:
                requests.get(new_url())
            except ConnectionError:
                returnedError = ConnectionError
            self.assertEqual(returnedError, ConnectionError)
        self.assertEqual(temp["retried"], max_tries)

    def test_custom_retry(self):
        temp = {"retried": -1}
        retries = random.randrange(1, Config.cb_fail_threshold(), 1)

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(new_url(), max_tries=retries)
            except ConnectionError as e:
                self.assertTrue(str(e) != "Open Circuit")
            else:
                raise Exception("Should have raised ConnectionError")
        self.assertEqual(temp["retried"], retries)

    def test_no_retry(self):
        temp = {"retried": -1}

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(new_url(), max_tries=0)
            except ConnectionError as e:
                self.assertTrue(str(e) != "Open Circuit")
            else:
                raise Exception("Should have raised ConnectionError")
        self.assertEqual(temp["retried"], 0)

    def test_retry_only_for_retriable_exceptions(self):
        temp = {"retried": -1}
        retries = 2

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise KeyError("custom")

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(new_url(), max_tries=retries)
            except KeyError:
                pass
        self.assertEqual(temp["retried"], 0)


class TestCircuitBreaking(unittest.TestCase):
    def setUp(self):
        pyhystrix.Init()

    def test_default_circuitbreaking(self):
        temp = {"retried": 0}
        cb_threshold = Config.cb_fail_threshold()
        retries = cb_threshold + 2
        url = new_url()

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(url, max_tries=retries)
            except ConnectionError as e:
                self.assertTrue(str(e) != "Open Circuit")
            else:
                raise Exception("Should have raised ConnectionError")
        self.assertEqual(temp["retried"], cb_threshold)

        try:
            requests.get(url)
        except ConnectionError as e:
            self.assertTrue(str(e), "Open Circuit")
        else:
            raise Exception("Should have raised ConnectionError")

        time.sleep(Config.cb_delay())
        temp["retried"] = 0

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(url, max_tries=retries)
            except ConnectionError as e:
                self.assertTrue(str(e) != "Open Circuit")
            else:
                raise Exception("Should have raised ConnectionError")
        self.assertEqual(temp["retried"], 1)

    def test_custom_circuitbreaking(self):
        custom_threshold = random.randrange(2, 4, 1)
        custom_delay = 5
        os.environ["PYH_CIRCUIT_FAIL_THRESHOLD"] = str(custom_threshold)
        os.environ["PYH_CIRCUIT_DELAY"] = str(custom_delay)

        pyhystrix.Init()

        temp = {"retried": 0}
        retries = custom_threshold + 2
        url = new_url()

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(url, max_tries=retries)
            except ConnectionError:
                pass
        self.assertEqual(temp["retried"], custom_threshold)

        time.sleep(custom_delay)
        temp["retried"] = 0

        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(url, max_tries=retries)
            except ConnectionError:
                pass
            self.assertEqual(temp["retried"], 1)

        del os.environ["PYH_CIRCUIT_FAIL_THRESHOLD"]
        del os.environ["PYH_CIRCUIT_DELAY"]

    def test_circuit_half_open_after_alive_threshold(self):
        temp = {"retried": 0}
        url = new_url()
        cb_threshold = Config.cb_fail_threshold()

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        with CustomFailureMock(_fake_new_conn):
            # Open the circuit
            try:
                requests.get(url, max_tries=cb_threshold+2)
            except ConnectionError:
                pass
            self.assertEqual(temp["retried"], cb_threshold)

            # reset the counter
            temp["retried"] = 0
            # Make requests on open circuit till the alive_threshold is reached
            # and the circuit is half open
            for i in range(Config.cb_alive_threshold()):
                try:
                    requests.get(url)
                except ConnectionError:
                    self.assertEqual(temp["retried"], 0)
                else:
                    raise Exception("Should have raised ConnectionError")

            try:
                requests.get(url)
            except ConnectionError:
                pass
            self.assertEqual(temp["retried"], 1)

    def test_circuit_closed_on_success(self):
        """Steps:
        1. Open the circuit with failed calls. Even thought he retry count is
           more that cb_failure_threshold, the actual call count only reaches
           the cb_failure_threshold and no request is made on the closed
           circuit
        2. make the circuit half open by making failed calls on open circuit
           to reach cb_fail_threshold
        3. Make a success call on half open circuit to close it
        4. make failed requests on closed circuit and check the count to
           validate that the circuit was closed
        """
        temp = {"retried": 0}
        url = new_url()
        cb_threshold = Config.cb_fail_threshold()

        def _fake_new_conn(self):
            temp["retried"] += 1
            raise ConnectTimeoutError(self, "", (self.host,
                                                 self.timeout))

        @all_requests
        def success_handler(url, request):
            return "Success"

        with CustomFailureMock(_fake_new_conn):
            # Open the circuit
            try:
                requests.get(url, max_tries=cb_threshold+2)
            except ConnectionError:
                pass
            self.assertEqual(temp["retried"], cb_threshold)

            # Make circuit half open
            for i in range(Config.cb_alive_threshold()):
                try:
                    requests.get(url)
                except ConnectionError:
                    pass
                else:
                    raise Exception("Should have raised ConnectionError")

        with HTTMock(success_handler):
            requests.get(url)

        temp["retried"] = 0
        cb_threshold = Config.cb_fail_threshold()
        with CustomFailureMock(_fake_new_conn):
            try:
                requests.get(url, max_tries=cb_threshold+2)
            except ConnectionError:
                pass
            self.assertEqual(temp["retried"], cb_threshold)

    def test_retry_put_on_500(self):
        counter = {"retried": 0}
        cb_threshold = Config.cb_fail_threshold()

        with CustomHTTPResponseMock(counter, 500):
            # Open the circuit
            try:
                requests.put(new_url(), max_tries=cb_threshold+2)
            except RetryError:
                pass
            self.assertEqual(counter["retried"], cb_threshold)

    def test_no_default_retry_on_put(self):
        counter = {"retried": 0}

        with CustomHTTPResponseMock(counter, 400):
            # Open the circuit
            try:
                requests.put(new_url())
            except RetryError:
                pass
            self.assertEqual(counter["retried"], 1)

    def test_default_retry_on_get_500(self):
        counter = {"retried": -1}
        max_tries = Config.max_tries()

        with CustomHTTPResponseMock(counter, 500):
            # Open the circuit
            try:
                requests.get(new_url())
            except RetryError:
                pass
        self.assertEqual(counter["retried"], max_tries)


class TestLogger(unittest.TestCase):
    def setUp(self):
        pyhystrix.Init()
        self.handler = CustomLogHandler()
        logger.addHandler(self.handler)

    def test_emit_logs_on_DEBUG_level(self):
        url = new_url()

        try:
            requests.get(url)
        except ConnectionError:
            pass
        self.assertEqual(self.handler.emit_count, 0)

        logger.setLevel(logging.DEBUG)

        try:
            requests.get(url)
        except ConnectionError:
            pass
        print(self.handler.emit_count)
        self.assertTrue(self.handler.emit_count > 0)

    def tearDown(self):
        logger.handlers.remove(self.handler)
        logger.setLevel(logging.WARNING)


class TestBreaker(unittest.TestCase):
    def setUp(self):
        self.breaker = circuit_breaker.CircuitBreaker(
            allowed_fails=DEFAULT_FAILS,
            retry_time=DEFAULT_RETRY,
            retry_after=DEFAULT_OPEN_CIRCUIT_THREASHOLD,
            validation_func=None
        )
        self.breaker_with_validation = circuit_breaker.CircuitBreaker(
            allowed_fails=DEFAULT_FAILS,
            retry_time=DEFAULT_RETRY,
            validation_func=validation_stub
        )
        self.breaker_with_allowed = circuit_breaker.CircuitBreaker(
            allowed_exceptions=[AttributeError]
        )
        self.breaker_with_fail_exc = circuit_breaker.CircuitBreaker(
            failure_exceptions=[KeyError]
        )

    def test_open_transition(self):
        breaker = self.breaker
        for i in range(DEFAULT_FAILS):
            breaker._on_failure()
        self.assertEqual(breaker._state, circuit_breaker.OPEN)
        self.assertEqual(breaker._failure_count, DEFAULT_FAILS)

    def test_success(self):
        breaker = self.breaker
        for i in range(DEFAULT_FAILS - 1):
            breaker._on_failure()
        self.assertEqual(breaker._state, circuit_breaker.CLOSED)
        self.assertEqual(breaker._failure_count, DEFAULT_FAILS - 1)

        breaker._on_success()
        self.assertEqual(breaker._state, circuit_breaker.CLOSED)
        self.assertEqual(breaker._failure_count, 0)

    def test_half_open(self):
        breaker = self.breaker
        for i in range(DEFAULT_FAILS):
            breaker._on_failure()
        self.assertEqual(breaker._state, circuit_breaker.OPEN)

        time.sleep(DEFAULT_RETRY)
        breaker._check_state()
        self.assertEqual(breaker._state, circuit_breaker.HALF_OPEN)

    def test_open_threashold(self):
        breaker = self.breaker
        breaker._close()
        for i in range(DEFAULT_FAILS):
            breaker._on_failure()
        self.assertEqual(breaker._state, circuit_breaker.OPEN)

        for i in range(DEFAULT_OPEN_CIRCUIT_THREASHOLD):
            try:
                breaker._call(raises_something, KeyError())
            except Exception:
                pass
        breaker._check_state()
        self.assertEqual(breaker._state, circuit_breaker.HALF_OPEN)

    def test_validation_func(self):
        breaker = self.breaker_with_validation
        fake_result = 0
        breaker._parse_result(fake_result)
        self.assertEqual(breaker._failure_count, 1)
        # breaker should reset count upon success
        fake_result = 1
        breaker._parse_result(fake_result)
        self.assertEqual(breaker._failure_count, 0)

    def test_no_validation_func(self):
        breaker = self.breaker
        fake_result = 0
        breaker._parse_result(fake_result)
        self.assertEqual(breaker._failure_count, 0)
        fake_result = 1
        breaker._parse_result(fake_result)
        self.assertEqual(breaker._failure_count, 0)

    def test_parse_allowed_exc(self):
        breaker = self.breaker_with_allowed
        breaker._call(raises_something, KeyError())
        self.assertEqual(breaker._failure_count, 1)
        breaker._call(raises_something, AttributeError())
        # not a success, but not a failure either
        self.assertEqual(breaker._failure_count, 1)

    def test_parse_failure_exc(self):
        breaker = self.breaker_with_fail_exc
        breaker._call(raises_something, KeyError())
        self.assertEqual(breaker._failure_count, 1)
        breaker._call(raises_something, AttributeError())
        # not a success, but not a failure either
        self.assertEqual(breaker._failure_count, 1)

    def test_handles_child_exc(self):
        class TestException(AttributeError):
            pass
        breaker = self.breaker_with_allowed
        breaker._call(raises_something, TestException())
        self.assertEqual(breaker._failure_count, 0)

    def test_init_failure(self):
        args = []
        kwargs = {
            "allowed_fails": DEFAULT_FAILS,
            "retry_time": DEFAULT_RETRY,
            "allowed_exceptions": [ValueError, AttributeError],
            "failure_exceptions": [KeyError]
        }
        self.assertRaises(ValueError, circuit_breaker.CircuitBreaker, *args,
                          **kwargs)


if __name__ == '__main__':
    unittest.main()
