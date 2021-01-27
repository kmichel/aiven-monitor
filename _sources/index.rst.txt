aiven-monitor documentation
=========================================

Website monitoring with Kafka and Postgres.

The project is split in two programs:

 - ``aiven-monitor-checker`` : runs the monitoring probes and sends the result to Kafka.
 - ``aiven-monitor-writer`` : reads from Kafka and stores the result in Postgres.

Links
=====

- `Github Repository <https://github.com/kmichel/aiven-monitor/>`__
- `Tests <./tests/>`__
- `Coverage <./coverage/>`__

.. toctree::
    :caption: Configuration

    configuration.rst

.. toctree::
    :caption: API Reference

    aiven_monitor.rst

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
