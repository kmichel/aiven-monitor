FROM debian:buster-slim
RUN \
    mkdir -p /usr/share/man/man1 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    openjdk-11-jre-headless \
    wget \
    && rm -rf /var/lib/apt/lists/*
COPY kafka_2.13-2.7.0.tgz.sha512 .
RUN \
    wget --no-verbose  --output-document kafka_2.13-2.7.0.tgz \
        'https://www.apache.org/dyn/closer.cgi?filename=kafka/2.7.0/kafka_2.13-2.7.0.tgz&action=download' \
    && sha512sum --check kafka_2.13-2.7.0.tgz.sha512 \
    && tar xf kafka_2.13-2.7.0.tgz \
    && rm kafka_2.13-2.7.0.tgz*
WORKDIR kafka_2.13-2.7.0
RUN \
    groupadd -r aiven --gid=999 \
	&& useradd -r -g aiven --uid=999 --system --shell=/bin/false aiven \
	&& install --owner=aiven --group=aiven --directory ./logs
