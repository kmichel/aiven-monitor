.. module:: aiven_monitor.checker

checker
=======

This module connects to a list of websites at regular interval and records
connection metrics into a Kafka topic.

In addition to the classes documented below, this can be called from the
command line as `aiven-monitor-checker` or `python -m aiven_monitor.checker`.

Configuration Options
---------------------

The configuration options are read from `/run/secrets/reader.ini` using :class:`ConfigParser`.

All the following settings must be in a **[checker]** section of the ini file.

- **endpoint**: A name for the location from where the checker is run. Default value is "default".
- **kafka.bootstrap_servers**: A comma-separated list of Kafka servers. Will connect to "localhost:9092" if not configured.
- **kafka.topic**: The Kafka topic receiving the produced :class:`aiven_monitor.Measure` objects. Default value is "aiven_monitor_measure".
- **kafka.ssl.cafile**: The path to the PEM certificate of the certificate authority used to authenticate the Kafka servers. Optional.
- **kafka.ssl.certfile**: The path to the PEM certificate used to authenticate the checker. Optional.
- **kafka.ssl.keyfile**: The path to the PEM private key used to authenticate the checker. Optional.
- **kafka.connect_interval_secs**: The number of seconds before retrying to connect. Default value is `1.0`.

Entry Points
------------

.. autofunction:: aiven_monitor.checker.main

.. autofunction:: aiven_monitor.checker.async_main

Probe
-----

.. autoclass:: aiven_monitor.checker.Probe
    :members:

Schedule
--------

.. autoclass:: aiven_monitor.checker.Schedule
    :members:

Scheduler
---------

.. autoclass:: aiven_monitor.checker.Scheduler
    :members:

KafkaRecorder
-------------

.. autoclass:: aiven_monitor.checker.KafkaRecorder
    :members:
