# pyhystrix

### A library to patch requests package in order to add following functionalities by default:

- Connection and Read timeouts
- Retries on connection failure
- Circuitbreaking
- Adding unique `x-request-id` in request header if not provided

Installation
------------

```sh
pip install pyhystrix
```

Usage
-----
Before making any request, just call `Init()`:

```python
import requests
import pyhystrix
requests.get("http://abc.xyx") // No functionalities of pyhystrix
pyhystrix.Init()
requests.get("http://abc.xyx") // pyhystrix is attached to all requests
```

Default Configurations can be changed in 2 ways:

1. Setting following env variables:
	- `PHY_CONNECT_TIMEOUT` : connection timeout in sec
	- `PHY_READ_TIMEOUT`: read timeout in seconds
	- `PHY_MAX_RETRIES`: max number of retries for connection failure
	- `PHY_CIRCUIT_FAIL_THRESHOLD`: Number of failed requests after which circuit will be open and further requests on the same url will not be allowed.
	- `PHY_CIRCUIT_ALIVE_THRESHOLD`: Number of failed requests on open circuit to make it half_open (Described below)
	- `PHY_CIRCUIT_DELAY`: Number of seconds after which open circuit will be half_open.

2. parameters in request itself:
	- `max_tries`(int): overrides `PHY_MAX_RETRIES`, some rules related to it are follows:
		- `max_tries=0`: will cause no retries, fail on first failure.
		- If a positive value is passed for non `GET` requests, they will be retried too in case received status is in `status_forcelist`.
	- `status_forcelist`: list of http status, retry if the returned status is one of these. default is `[500]` on `GET`.
	- `timeout`: same as timeout in [requests](http://docs.python-requests.org/en/master/user/advanced/#timeouts)
	- `backoff_factor`: delay in each retry will be affected by this using following formula: ```{backoff factor} * (2 ^ ({number of total retries} - 1))```. Default = `0.5`sec

More Examples
-------------
- `GET` with retry on multiple failure status codes:

```python
import requests
import pyhystrix
pyhystrix.Init()
request.get("http://abc.xyz", status_forcelist=[501, 502, 403])
```

- `put` with retry on response status = `500` or `501`

```python
request.put("http://abc.xyz", max_tries=3, status_forcelist=[500, 502])
```

**NOTE:** All type of requests will be retried in case of `ConnectionError`

Circuit Breaker States
---------------
1. **OPEN** : No requests will be allowed
2. **HALF_OPEN** : Only one request will be allowed
3. **CLOSE** : All requests will be allowed.

**NOTE** : State transitions:

`CLOSE --> OPEN --> HALF_OPEN --> CLOSE/OPEN`

### To know more about circuit breaker pattern, click [here](https://martinfowler.com/bliki/CircuitBreaker.html)
