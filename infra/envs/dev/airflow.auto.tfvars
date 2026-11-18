# The Airflow host's first release. Later releases are deployed through SSM, not Terraform.
airflow_image  = "097040011808.dkr.ecr.us-east-1.amazonaws.com/earnings-watch-dev/airflow:cc6eaecdc144"
spark_code_uri = "s3://earnings-watch-dev-097040011808/artifacts/spark/7306a4d2facc"
