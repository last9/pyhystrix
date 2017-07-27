# pyhystrix

### A library to patch requests package in order to add following functionalities by default:

- Connection and Read timeouts
- Retries on connection failure
- Circuitbreaking
- Adding unique reques-id in request header if not provided

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
	- `PHY_READ_TIMEOUT`: read timeout in sec
	- `PHY_MAX_RETRIES`: max number of retries for connection failure
	- `PHY_CB_FAIL_THRESHOLD`: Number of failed requests after which circuit will be open and further requests on the same url will not be allowed.
	- `PHY_CB_ALIVE_THRESHOLD`: Number of failed requests on open circuit to make it half_open (Described below)
	- `PHY_CB_DELAY`: Number of sec after which open circuit will be half_open.

2. parameters in request itself:
	- `retries`(int): overrides `PHY_MAX_RETRIES `
	- `timeout`: same as timeout in [requests](http://docs.python-requests.org/en/master/user/advanced/#timeouts)

Circuit Breaker States
---------------
1. **OPEN** : No requests will be allowed
2. **HALF_OPEN** : Only one request will be allowed
3. **CLOSE** : All requests will be allowed.

**NOTE** : State transitions:

`CLOSE --> OPEN --> HALF_OPEN --> CLOSE/OPEN`

### To know more about circuit breaker pattern, click [here](https://martinfowler.com/bliki/CircuitBreaker.html)
