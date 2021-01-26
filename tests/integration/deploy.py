#!/usr/bin/env python
import secrets
import tempfile
import time
from pathlib import Path
from subprocess import run
from typing import Optional

'''
This code builds a whole Docker stack with Kafka, Zookeeper, Postgres and our
own code. 

The requirements are :
 - Docker
 - Docker Swarm : `docker swarm init` to start a swarm on a non-swarm node.
 - OpenSSL
 - keytool : this is part of any Java distribution (OpenJRE for instance).

The stack is defined in the docker-compose.yml file next to this file.

The SSL certificates to authenticate all services are generated here, with a
bit of care to avoid leaking them through process arguments. Managing
SSL keys is 90% of the work done here.

The SSL keystores, truststores, passwords, etc... are all stored as Docker
Secrets (That's why we use Docker Swarm and not simply docker-compose). 

The configuration files for each service are also generated here: 
 - We use the templates .properties and .ini files in this folder
 - Then replace the placeholders for the various passwords
 - Then save them as Docker Secrets.

The whole stack and all associated Docker Secrets are removed and
recreated each time this program runs.
'''


def main():
    this_folder = Path(__file__).parent
    validity_days = 2
    stack_name = 'aiven-monitor-test'
    roles = ['kafka', 'zookeeper', 'checker', 'writer', 'postgres']
    docker('stack', 'rm', stack_name, check=False)
    docker('build', '-t', 'aiven-monitor-kafka', this_folder / 'kafka')
    docker('build', '-t', 'aiven-monitor', this_folder.parent.parent)
    postgres_password = secrets.token_hex()
    create_secret('postgres.password', postgres_password.encode())
    with tempfile.TemporaryDirectory() as ca_dir:
        ca_dir = Path(ca_dir)
        ca_key_pass = secrets.token_hex()
        ca_key_path = ca_dir / 'ca.private.pem'
        ca_cert_path = ca_dir / 'ca.certificate.pem'
        create_ca(ca_key_pass, ca_key_path, ca_cert_path, validity_days)
        for role in roles:
            create_role(
                role, ca_key_pass, ca_key_path, ca_cert_path, validity_days
            )
    wait_for_docker_network_removal(stack_name)
    docker('stack', 'deploy', stack_name, '--compose-file=docker-compose.yml')


def docker(*args, check=True, **kwargs) -> Optional[bytes]:
    process = run(['docker', *args], check=check, **kwargs)
    if kwargs.get('capture_output'):
        return process.stdout


def wait_for_docker_network_removal(stack_name):
    while True:
        stack_filter = f'label=com.docker.stack.namespace={stack_name}'
        lines = docker(
            'network', 'ls', '--filter', stack_filter, '-q', capture_output=True
        )
        if b'\n' in lines:
            time.sleep(1)
        else:
            break


def create_ca(ca_key_pass, ca_key_path, ca_cert_path, validity_days):
    run(
        [
            'openssl',
            'req',
            '-new',
            '-x509',
            '-newkey',
            'rsa:4096',
            '-subj',
            '/CN=CA',
            '-passout',
            'stdin',
            '-keyout',
            ca_key_path,
            '-out',
            ca_cert_path,
            '-days',
            str(validity_days),
        ],
        input=ca_key_pass.encode(),
        check=True,
    )
    create_secret_from_file('ca.certificate.pem', ca_cert_path)


def create_role(role, ca_key_pass, ca_key_path, ca_cert_path, validity_days):
    with tempfile.TemporaryDirectory() as work_dir:
        work_dir = Path(work_dir)
        cert_request_path = work_dir / 'request.pem'
        cert_signed_path = work_dir / 'signed.pem'
        truststore_jks = work_dir / 'truststore.jks'
        keystore_jks = work_dir / 'keystore.jks'
        keystore_p12 = work_dir / 'keystore.p12'
        keystore_pem = work_dir / 'keystore.pem'
        role_store_pass = secrets.token_hex()
        # ZooKeeper does not support setting the key password in the ZooKeeper
        # server keystore to a value different from the keystore password
        # itself.
        role_key_pass = role_store_pass
        with tempfile.NamedTemporaryFile() as role_store_pass_file:
            role_store_pass_file.write(role_store_pass.encode())
            role_store_pass_file.flush()
            keytool(
                'importcert',
                'trustcacerts',
                'noprompt',
                keystore=truststore_jks,
                file=ca_cert_path,
                storepass_file=role_store_pass_file.name,
            )
            keytool(
                'genkeypair',
                keystore=keystore_jks,
                alias=role,
                keyalg='RSA',
                validity=str(validity_days),
                dname=f'CN={role}',
                ext=f'SAN=DNS:{role}',
                storepass_file=role_store_pass_file.name,
                keypass_file=role_store_pass_file.name,
            )
            keytool(
                'certreq',
                keystore=keystore_jks,
                alias=role,
                file=cert_request_path,
                storepass_file=role_store_pass_file.name,
                keypass_file=role_store_pass_file.name,
            )
            # TODO: use gencert
            run(
                [
                    'openssl',
                    'x509',
                    '-req',
                    '-CA',
                    ca_cert_path,
                    '-CAkey',
                    ca_key_path,
                    '-in',
                    cert_request_path,
                    '-out',
                    cert_signed_path,
                    '-days',
                    str(validity_days),
                    '-CAcreateserial',
                    '-passin',
                    'stdin',
                ],
                input=ca_key_pass.encode(),
                check=True,
            )
            keytool(
                'importcert',
                'noprompt',
                keystore=keystore_jks,
                file=ca_cert_path,
                storepass_file=role_store_pass_file.name,
            )
            keytool(
                'importcert',
                'noprompt',
                keystore=keystore_jks,
                file=cert_signed_path,
                alias=role,
                storepass_file=role_store_pass_file.name,
                keypass_file=role_store_pass_file.name,
            )
            keytool(
                'importkeystore',
                srckeystore=keystore_jks,
                destkeystore=keystore_p12,
                srcstorepass_file=role_store_pass_file.name,
                deststorepass_file=role_store_pass_file.name,
                deststoretype='pkcs12',
            )
            run(
                [
                    'openssl',
                    'pkcs12',
                    '-passin',
                    'stdin',
                    '-passout',
                    f'file:{role_store_pass_file.name}',
                    '-in',
                    keystore_p12,
                    '-out',
                    keystore_pem,
                ],
                input=role_store_pass.encode(),
                check=True,
            )
            private_key = run(
                [
                    'openssl',
                    'rsa',
                    '-passin',
                    'stdin',
                    '-in',
                    keystore_pem,
                    '-out',
                    '-',
                ],
                input=role_store_pass.encode(),
                capture_output=True,
                check=True,
            ).stdout
            create_secret_from_file(f'{role}.certificate.pem', cert_signed_path)
            create_secret(f'{role}.private.pem', private_key)
            create_secret_from_file(f'{role}.truststore.jks', truststore_jks)
            create_secret_from_file(f'{role}.keystore.jks', keystore_jks)
            for extension in 'ini', 'properties':
                try:
                    with open(f'{role}.{extension}') as config_file:
                        config = config_file.read()
                        config = config.replace(
                            f'{role.upper()}_STORE_PASSWORD', role_store_pass
                        )
                        config = config.replace(
                            f'{role.upper()}_KEY_PASSWORD', role_key_pass
                        )
                        create_secret(f'{role}.{extension}', config.encode())
                except FileNotFoundError:
                    pass


def create_secret(name, value):
    docker('secret', 'rm', name, check=False)
    docker('secret', 'create', name, '-', input=value)


def create_secret_from_file(name, filename):
    docker('secret', 'rm', name, check=False)
    docker('secret', 'create', name, filename)


def keytool(*args, **kwargs):
    run(
        [
            'keytool',
            *[f'-{arg}' for arg in args],
            *[
                arg
                for key, value in kwargs.items()
                for arg in (f"-{key.replace('_', ':')}", value)
            ],
        ],
        check=True,
    )


if __name__ == '__main__':
    main()
