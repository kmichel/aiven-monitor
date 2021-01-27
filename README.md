# Aiven Monitor

  - [API Reference](https://kmichel.github.io/aiven-monitor/)
  - [Tests](https://kmichel.github.io/aiven-monitor/tests/)
  - [Coverage](https://kmichel.github.io/aiven-monitor/coverage/)
  - Compatible with Python 3.7, 3.8 and 3.9

Website monitoring with Kafka and Postgres.

The project is split in two binaries:
 - `aiven-monitor-checker` : runs the monitoring probes and sends the result to Kafka.
 - `aiven-monitor-writer` : reads from Kafka and stores the result in Postgres.

The monitoring probes are [configurable from a file](https://kmichel.github.io/aiven-monitor/configuration.html#probes-ini):

```ini
[probe.aiven]
url = https://www.aiven.io
interval_secs = 20
expected_pattern = Perf.?rmant|\bFree\b|Scalable
[probe.github]
url = https://www.github.com
interval_secs = 60
[probe.google]
url = https://www.google.fr
interval_secs = 120
```

# Dev Setup
```shell script
python3 -m venv --clear --upgrade-deps venv
source venv/bin/activate
venv/bin/pip install --constraint constraints.txt --requirement dev-requirements.txt
```

# Containerized Demo
This runs local Postgres and Kafka instances along with the checker and writer.

This still requires Python, OpenSSL and keytool (from the Java JRE/JDK) in addition to Docker.

Docker Swarm is used to handle SSL secrets between the different services.
```shell script
docker swarm init
tests/integration/deploy.py
docker service logs aiven-monitor-test_writer --timestamps 2>&1 -f
```

# Running the Checker
See the [Checker documentation](https://kmichel.github.io/aiven-monitor/configuration.html#checker-ini) for the configuration options. 
```shell script
aiven-monitor-checker --config=/path/to/checker.ini
```

# Running the Writer
See the [Writer documentation](https://kmichel.github.io/aiven-monitor/aiven_monitor/configuration.html#writer-ini) for the configuration options.
```shell script
aiven-monitor-writer --config=/path/to/writer.ini
```

# Running Tests & Building Docs
The tests are also configured with Github Actions to run against real [Aiven](https://aiven.io) services after each push.
```shell script
pytest
sphinx-build -a docs target/docs
``` 
