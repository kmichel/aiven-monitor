# Aiven Monitor
Monitor website status and send to Kafka.

# Dev Setup
```shell script
python3 -m venv venv
source ven/bin/activate
pip install --upgrade pip setuptools wheel
pip install --upgrade --editable .[speedups]
```

# Tests & Docs
```shell script
pip install --upgrade --constraint constraints.txt --requirement docs/requirements.txt
pip install --upgrade --constraint constraints.txt --requirement tests/requirements.txt
pytest
coverage html
sphinx-build -a docs target/docs
``` 
