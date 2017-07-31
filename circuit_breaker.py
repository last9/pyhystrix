'''
Module for fault tolerance handling using Finite State Machines (FSM)

Circuit breakers prevent additional load from being cast on an ailing systems
and provide graceful degradation of services to consumers of the ailing system.
They function by switching between 3 states:
    Closed:    Healthy normal state
    Open:      Unhealthy state, do not allow any traffic through
    Half Open: Send one test request through, and open or close based
               on the result of the test

Example Use:
    @CircuitBreaker(allowed_fails=2, retry_time=10, retry_after=50)
    def request_to_service():
        # send http request to other system...

    If exceptions are encountered by request_to_service, they will increment
    the internal failure counter of CircuitBreaker until it hits the
    allowed_fails specified by the user. At this point the breaker will
    spring open and not let anymore requests occur until the breaker is
    set to the half open state when retry_time has passed in seconds or
    number of requests on open circuit crosses retry_after (whatever happens
    first)

'''
import time
import functools
import threading
from config import logger
from requests.exceptions import ConnectionError

CLOSED = 0
OPEN = 1
HALF_OPEN = 2


class CircuitBreaker(object):
    '''FSM to allow fault tolerance when systems fail'''
    def __init__(self, allowed_fails=3, retry_time=30, retry_after=50,
                 validation_func=None, allowed_exceptions=None,
                 failure_exceptions=None):
        '''
        Initializes Breaker object

        Args:
            allowed_fails(int): Maximum number of consecutive failures allowed
                before opening circuit
            retry_time(int): Number of seconds during close period before
                allowing test request to check if other end of circuit is
                responsive
            retry_after(int): Number of max failed requests on open circuit
                after which the circuit will be half_open irrespective of
                retry_time
            validation_func(func): function to check if return value of wrapped
                function is permissible. Must return boolean value
                allowed_exceptions(list[Exception]): permissible exceptions
                that will not trigger a failure. Do not use in conjunction with
                failure_exceptions. Will also check for child exceptions of the
                ones provided here. If these exceptions are caught, they will
                not be counted as a success either, and will not change the
                state of the FSM
            failure_exceptions(list[Exception]): if provided, only these
                exceptions will be registered as failures. Do not use in
                conjunction with allowed_exceptions. Will also check for child
                exceptions of the ones provided
        '''
        self._allowed_fails = allowed_fails
        self._retry_time = retry_time
        self._validation_func = validation_func
        self._lock = threading.Lock()
        self._read_lock = threading.RLock()
        self._failure_count = 0
        self._open_circuit_failure_count = 0
        self._open_circuit_failure_threashold = retry_after
        self._state = CLOSED
        self._half_open_time = 0  # initialize to minimum seconds since epoch
        if allowed_exceptions is not None:
            self._allowed_exceptions = tuple(allowed_exceptions)
        else:
            self._allowed_exceptions = ()

        if failure_exceptions is not None:
            self._failure_exceptions = tuple(failure_exceptions)
        else:
            self._failure_exceptions = ()

        if self._failure_exceptions and self._allowed_exceptions:
            raise ValueError("Cannot set failure exceptions in tandem with "
                             "allowed_exceptions")

    def _open(self):
        '''Open the circuit breaker and set time for half open'''
        self._state = OPEN
        open_time = time.time()
        self._half_open_time = open_time + self._retry_time
        self._open_circuit_failure_count = 0
        logger.info("Circuit breaker opened")

    def _close(self):
        '''Close circuit breaker and reset failure count'''
        self._state = CLOSED
        self._failure_count = 0
        self._open_circuit_failure_count = 0
        logger.info("Circuit breaker closing, reset failure count")

    def _half_open(self):
        ''' Set circuit breaker to half open state'''
        self._state = HALF_OPEN
        logger.info("Circuit breaker half open")

    def _check_state(self):
        '''Check current state of breaker and set half open when possible'''
        if self._state == OPEN:
            now = time.time()
            if now >= self._half_open_time or \
                self._open_circuit_failure_count >= \
                    self._open_circuit_failure_threashold:
                self._half_open()

        return self._state

    def _on_failure(self):
        '''
        Increments failure counter and switches state if allowed_fails is
        reached
        '''
        self._failure_count += 1
        logger.debug("Failure encountered, failure count: {}".
                     format(self._failure_count))
        if self._failure_count >= self._allowed_fails:
            current_state = self._check_state()
            if current_state != OPEN:
                self._open()

    def _on_success(self):
        '''
        Moves breaker to closed state
        '''
        self._close()

    def _parse_result(self, result):
        '''
        Determine if result of wrapped function is valid

        Args:
            result(object): return value of wrapped function
        '''
        if self._validation_func is None:
            self._on_success()
            return

        if self._validation_func(result):
            self._on_success()
        else:
            self._on_failure()

    def _call(self, func, *args, **kwargs):
        '''
        Wraps decorated function and watches for successes and failures

        Args:
            func(function): decorated function
            *args: args passed to decorated function
            **kwargs: kwargs passed to decorated function
        '''
        with self._lock:
            current_state = self._check_state()
            if current_state == OPEN:
                self._open_circuit_failure_count += 1
                raise ConnectionError("Open circuit")
            try:
                result = func(*args, **kwargs)
            except self._allowed_exceptions as e:
                logger.info("Encountered allowed exception {}".
                            format(e.__class__))
                return  # not a failure, but not a success
            except self._failure_exceptions:
                logger.exception("Caught pre-defined failure exception")
                self._on_failure()
            except Exception as e:
                logger.exception("Caught unhandled exception, incrementing "
                                 "failure count")
                if self._failure_exceptions:
                    logger.info("Encountered non-failure exception {}".
                                format(e.__class__))
                    return  # not a failure, but not a success
                else:
                    self._on_failure()
            else:
                logger.debug("Successfully completed wrapped function")
                self._parse_result(result)

    def __call__(self, func):
        @functools.wraps(func)
        def wrapped_func(*args, **kwargs):
            return self._call(func, *args, **kwargs)

        return wrapped_func

    @property
    def is_open(self):
        with self._lock:
            return self._check_state() == OPEN

    def increment_failure_count(self):
        with self._lock:
            self._open_circuit_failure_count += 1

    def mark_failure(self):
        with self._lock:
            self._on_failure()

    def close(self):
        with self._lock:
            if self._check_state() != CLOSED:
                self._close()

    def __repr__(self):
        with self._read_lock:
            return ("Circuit Breaker - state: {state} fails: {fails} allowed "
                    "fails: {allowed} retry time: {retry_time} retry after: "
                    "{retry_after} failed requests".format(
                        state=self._state,
                        fails=self._failure_count,
                        allowed=self._allowed_fails,
                        retry_time=self._retry_time,
                        retry_after=self._open_circuit_failure_threashold)
                    )
