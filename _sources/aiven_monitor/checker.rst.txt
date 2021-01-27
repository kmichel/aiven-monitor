.. module:: aiven_monitor.checker

checker
=======

This module connects to a list of websites at regular interval and records
connection metrics into a Kafka topic.

This can be also run as ``aiven-monitor-checker`` or ``python -m aiven_monitor.checker`` :

.. code-block:: text

    usage: aiven-monitor-checker [-h] [--config CONFIG]

    Connects to a list of websites at regular interval and records connection metrics into a Kafka topic.

    optional arguments:
      -h, --help       show this help message and exit
      --config CONFIG  path to the config file. absolute or relative to the working directory. defaults to "checker.ini".

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
