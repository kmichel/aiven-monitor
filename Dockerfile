FROM python:3.9-buster as builder
RUN pip wheel psycopg2==2.8.6

FROM python:3.9-slim-buster
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends  libpq5 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR code
COPY --from=builder *.whl ./
COPY constraints.txt pyproject.toml setup.cfg setup.py ./
COPY src/aiven_monitor/version.py src/aiven_monitor/version.py
RUN \
    pip install *.whl \
    && pip install  --constraint constraints.txt .[speedups]
COPY src src
RUN pip install  --constraint constraints.txt .[speedups]
RUN \
    groupadd -r aiven --gid=999 \
	&& useradd -r -g aiven --uid=999 --system --shell=/bin/false aiven
STOPSIGNAL SIGINT
