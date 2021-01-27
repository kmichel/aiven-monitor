# Aiven Monitor

Monitor website status and send to Kafka then record to a Postgres database.

The checker is responsible for running the monitoring probes and sending to Kafka.

The writer is responsible for reading from Kafka and writing to Postgres.

  - [API Reference](https://kmichel.github.io/aiven-monitor/)
  - [Tests](https://kmichel.github.io/aiven-monitor/tests/)
  - [Coverage](https://kmichel.github.io/aiven-monitor/coverage/)

# Dev Setup
```shell script
python3 -m venv venv
source ven/bin/activate
pip install --upgrade pip setuptools wheel
pip install --upgrade --editable .[speedups]
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
See the [Checker documentation](https://kmichel.github.io/aiven-monitor/aiven_monitor/checker.html#configuration-options) for the configuration options. 
```shell script
aiven-monitor-checker --config=/path/to/checker.ini
```

# Running the Writer
See the [Writer documentation](https://kmichel.github.io/aiven-monitor/aiven_monitor/writer.html#configuration-options) for the configuration options.
```shell script
aiven-monitor-writer --config=/path/to/writer.ini
```

# Running Tests & Building Docs
The tests are also configured with Github Actions to run against real [Aiven](https://aiven.io) services after each push.
```shell script
pip install --upgrade --constraint constraints.txt --requirement docs/requirements.txt
pip install --upgrade --constraint constraints.txt --requirement tests/requirements.txt
pytest
coverage html
sphinx-build -a docs target/docs
``` 
