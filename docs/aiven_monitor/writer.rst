.. module:: aiven_monitor.writer

writer
======

This module collects Measure generated by the aiven-monitor
checker into a Kafka topic and records them in a Postgres database.

This can also be run as ``aiven-monitor-writer`` or ``python -m aiven_monitor.writer`` :

.. code-block:: text

    usage: aiven-monitor-writer [-h] [--config CONFIG]

    Collects measures generated by aiven-monitor-checker into a Kafka topic and records them in a Postgres database.

    optional arguments:
      -h, --help       show this help message and exit
      --config CONFIG  path to the config file. absolute or relative to the current working directory. defaults to "writer.ini".

Entry Points
------------

.. autofunction:: aiven_monitor.writer.main

.. autofunction:: aiven_monitor.writer.async_main

KafkaSource
------------------

.. autoclass:: aiven_monitor.writer.KafkaSource
    :members:

PostgresRecorder
----------------

.. autoclass:: aiven_monitor.writer.PostgresRecorder
    :members:
