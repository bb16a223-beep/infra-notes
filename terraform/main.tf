# 使うプロバイダーをと、そのバージョン指定
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0" #6系ならOK(7系は使わない）
    }
  }
}

# 無料プランだとシドニーしか使えないので、ap-southeast-2を指定
# tokyoだとSCPに拒否されて403になった

provider "aws" {
  region = "ap-southeast-2"
}

# 作らずに調べるだけのブロック：最新のAmazon Linux 2023のAMIを探す
# data = 聞くだけ
data "aws_ami" "al2023" {  # aws_ami:何を調べるか、al2023:これは調べものに付けた名前
  most_recent = true        # 一番新しいものから 
  owners      = ["amazon"]  # amazon公式の中から  

  # AMIの名前がal2023...で始まって、途中飛ばして-x86_64のを探して
  filter {
    name   = "name"         # name:項目 "name":名前の欄
    values = ["al2023-ami-2023.*-x86_64"] # この条件で探して
  }
}
# resource = 注文
resource "aws_instance" "lab" {
  ami                    = data.aws_ami.al2023.id # dataで調べたAMI (呼び名:al2023)のid
  instance_type          = "t3.micro"             # サーバの大きさ
  key_name               = aws_key_pair.lab.key_name  # 入るための鍵
  vpc_security_group_ids = [aws_security_group.ssh.id] # セキュリティルール 複数指定のための括弧

  #   vpc_security_group_ids = [
  #   aws_security_group.ssh.id,
  #   aws_security_group.web.id,
  # ] こんな感じに記載

  tags = {
    Name = "terraform-lab"    # コンソールから確認するための名前
  }                           # EC2はIDが名前の役割でありVPC内の重複ができないため、特別なタグを作成
}


# 手元の公開鍵をAWSに登録する
# file()はチルダを展開しないので、pathexpandが代わりに展開する関数らしい
resource "aws_key_pair" "lab" {
  key_name   = "terraform-lab"
  public_key = file(pathexpand("~/.ssh/terraform-lab.pub"))
}

# セキュリティグループ：SSHと8000番を、自分のIPだけに許可
# IPを変数にして、terraform.tfvarに分けた gitに載せないため
resource "aws_security_group" "ssh" {
  name        = "terraform-lab-ssh"   # AWSコンソールに出てくるSGの名前
  description = "SSH form my IP only" # 説明文

  # 入ってくる通信のルール
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  # 入ってくる通信のルール
  ingress {
    description = "Flask app via nginx" # コンソールから見える説明
    from_port   = 8000                  # ポートの番号の始まり
    to_port     = 8000                  # ポートの番号の終わり
    protocol    = "tcp"                 # 通信の種類
    cidr_blocks = [var.my_ip]           # 誰からの通信を許可するのか。自分のIPだけ/32
  }
  # 出ていく通信のルール
  # AWSで作成するＳＧは、全部出ていけるルールがデフォだが、Terraformでの作成に限り、このルールがないため明示的に記載
  egress {    
    from_port   = 0                     # protocolが全部なので慣例的な目的での記載
    to_port     = 0                     # protocolが全部なので慣例的な目的での記載
    protocol    = "-1"                  # すべてのプロトコル
    cidr_blocks = ["0.0.0.0/0"]         # どこに行ってもいい
  }
}

