terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-2"
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}
resource "aws_instance" "lab" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.lab.key_name
  vpc_security_group_ids = [aws_security_group.ssh.id]

  tags = {
    Name = "terraform-lab"
  }
}

resource "aws_key_pair" "lab" {
  key_name   = "terraform-lab"
  public_key = file(pathexpand("~/.ssh/terraform-lab.pub"))
}

resource "aws_security_group" "ssh" {
  name        = "terraform-lab-ssh"
  description = "SSH form my IP only"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }
  ingress {
    description = "Flask app via nginx"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

