-- One-time bootstrap of a new Snowflake account, run by hand as ACCOUNTADMIN.
-- Everything else is built by Terraform as the TERRAFORM service user.
-- After this script, no human or pipeline uses ACCOUNTADMIN.
--
-- Replace <PASTE_PUBLIC_KEY> with the one-line public key:
--   grep -v "PUBLIC KEY" ~/.snowflake/keys/terraform_rsa_key.pub | tr -d '\n'

USE ROLE ACCOUNTADMIN;

-- 1. A hard monthly spending cap for the whole account, before anything can run.
--    50 credits is about 50 hours of an extra-small warehouse.
CREATE RESOURCE MONITOR IF NOT EXISTS RM_ACCOUNT_MONTHLY
  WITH CREDIT_QUOTA = 50
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 75 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND
           ON 110 PERCENT DO SUSPEND_IMMEDIATE;
ALTER ACCOUNT SET RESOURCE_MONITOR = RM_ACCOUNT_MONTHLY;

-- 2. The trial's default warehouse idles for 10 minutes before suspending: make it 1.
ALTER WAREHOUSE IF EXISTS COMPUTE_WH SET AUTO_SUSPEND = 60;

-- 3. Terraform's role: build databases and warehouses (SYSADMIN), roles, users and
--    grants (SECURITYADMIN), and the S3 storage integration. Not ACCOUNTADMIN.
CREATE ROLE IF NOT EXISTS TERRAFORM_ADMIN COMMENT = 'Used only by Terraform';
GRANT ROLE SYSADMIN TO ROLE TERRAFORM_ADMIN;
GRANT ROLE SECURITYADMIN TO ROLE TERRAFORM_ADMIN;
GRANT CREATE INTEGRATION ON ACCOUNT TO ROLE TERRAFORM_ADMIN;

-- 4. Terraform's identity: a service user that can only log in with its key pair.
CREATE USER IF NOT EXISTS TERRAFORM
  TYPE = SERVICE
  DEFAULT_ROLE = TERRAFORM_ADMIN
  RSA_PUBLIC_KEY = '<PASTE_PUBLIC_KEY>'
  COMMENT = 'Terraform only: key-pair login, no password';
GRANT ROLE TERRAFORM_ADMIN TO USER TERRAFORM;

-- 5. Check.
SHOW RESOURCE MONITORS;
SHOW GRANTS TO ROLE TERRAFORM_ADMIN;
DESC USER TERRAFORM;
