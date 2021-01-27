.. module:: aiven_monitor.checker

checker
=======

This module connects to a list of websites at regular interval and records
connection metrics into a Kafka topic.

This can be run as as ``aiven-monitor-checker`` or ``python -m aiven_monitor.checker`` :

.. code-block:: text

    usage: aiven-monitor-checker [-h] [--config CONFIG]

    Connects to a list of websites at regular interval and records connection metrics into a Kafka topic.

    optional arguments:
      -h, --help       show this help message and exit
      --config CONFIG  path to the config file. absolute or relative to the working directory. defaults to "checker.ini".

Configuration Options
---------------------

The configuration options are read from a **reader.ini** file using :class:`ConfigParser`.

All the following settings must be in a **[checker]** section of the ini file.

.. code-block:: ini

    [checker]
    #  A name for the location from where the checker is run. Default value is "default".
    endpoint = default
    # A comma-separated list of Kafka servers. Will connect to "localhost:9092" if not configured.
    kafka.bootstrap_servers = "ocalhost:9092
    # Kafka topic receiving the produced Measure objects. Default value is "aiven_monitor_measure".
    kafka.topic = aiven_monitor_measure
    # Path to the PEM certificate of the authority used to authenticate the Kafka servers. Optional.
    kafka.ssl.cafile = /path/to/kafka.ca.pem
    # Path to the PEM certificate used to authenticate the checker. Optional.
    kafka.ssl.certfile = /path/to/kafka.certificate.pem
    # Path to the PEM private key used to authenticate the checker. Optional.
    kafka.ssl.keyfile = /path/to/kafka.private.pem
    # Number of seconds before retrying to connect. Default value is 1.0.
    kafka.connect_interval_secs = 1.0


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
