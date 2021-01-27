Checker
=======

checker.ini
----------

The configuration file for ``aiven-monitor-checker`` is usually named "checker.ini".

By default the program search for its configuration in the current working directory
but you can change that using the ``--config`` command-line option.

All the following settings must be in a **[checker]** section of the ini file.

The file paths, if relative, are relative to the path of the ini file.

.. code-block:: ini

    [checker]
    #  A name for the location from where the checker is run. Default value is "default".
    endpoint = default
    # Path to configuration file for the probes
    probes_file = probes.ini
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

probes.ini
----------

The probes are configured in a separate **probes.ini** file, with one section for each probe :

.. code-block:: ini

    [probe.aiven]
    # The URL to check
    url = https://aiven.io
    # The approximate interval between each check
    interval_secs = 60
    # A regular expression pattern to search in the response
    expected_pattern = Perf.?rmant
    [probe.google]
    url = https://www.google.com
    interval_secs = 120

Writer
======

writer.ini
----------

The configuration file for ``aiven-monitor-writer`` is usually named "writer.ini".

By default the program search for its configuration in the current working directory
but you can change that using the ``--config`` command-line option.

All the following settings must be in a **[writer]** section of the ini file.

The file paths, if relative, are relative to the path of the ini file.

.. code-block:: ini

    [writer]
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

    # Name of the table where measures are stored. Default value is "aiven_monitor_measure".
    postgres.measure_table = aiven_monitor_measure
    # Hostname of the Postgres server. Will connect to UNIX socket if not provided.
    postgres.host = localhost
    # Port of the Postgres server. Will connect through port 5432 if not provided and not a UNIX socket.
    postgres.port = 5432
    # Database inside the Postgres server. Will use to the same as the user name if not provided.
    postgres.database = postgres
    # User name to connect to the Postgres server.
    # Will use the same as the operating system name of the user running the application.
    postgres.user = postgres
    # Path to a text file with the password to connect to the Postgres server. Optional.
    postgres.passwordfile = /path/to/postgres.password
    # Path to the PEM certificate of the authority used to authenticate the Postgres server. Optional.
    postgres.ssl.rootcertfile = /path/to/postgres.ca.pem
    # Number of seconds before retrying to connect to Postgres. Default value is 1.0.
    postgres.connect_interval_secs = 1.0

