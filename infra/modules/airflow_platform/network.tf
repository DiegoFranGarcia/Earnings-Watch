# The network for the Airflow host: one public subnet, no NAT gateway, no inbound traffic.
#
# The host needs outbound HTTPS only (the SEC, Snowflake, S3, EMR, ECR, SSM, Discord). A public
# subnet with an auto-assigned address costs about $3.65 a month while the instance runs; a NAT
# gateway would cost about $33 a month before carrying a byte.

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "earnings-watch-${var.env}" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "earnings-watch-${var.env}" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "earnings-watch-${var.env}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "earnings-watch-${var.env}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# AWS gives every VPC a default security group that allows traffic between its members. Nothing
# uses it here, so it allows nothing.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
}

# The host's firewall: no inbound rules at all. The Airflow UI is reached through an SSM Session
# Manager tunnel, which the SSM agent opens from the inside; there is no SSH and no open port.
resource "aws_security_group" "host" {
  name        = "earnings-watch-${var.env}-airflow-host"
  description = "Airflow host: no inbound traffic; outbound HTTPS only"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "earnings-watch-${var.env}-airflow-host" }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.host.id
  description       = "HTTPS to the SEC, Snowflake, AWS APIs and Discord"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Certificate revocation checks (OCSP) use plain HTTP by design: the responses are signed, so they
# need no TLS. Without this rule, Snowflake's connector waited ~100 s for OCSP to time out on a cold
# cache, and its 60-second login token expired first: "JWT token is invalid" (2026-11-12).
resource "aws_vpc_security_group_egress_rule" "http_for_ocsp" {
  security_group_id = aws_security_group.host.id
  description       = "HTTP for certificate revocation checks (OCSP), whose responses are signed"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}
