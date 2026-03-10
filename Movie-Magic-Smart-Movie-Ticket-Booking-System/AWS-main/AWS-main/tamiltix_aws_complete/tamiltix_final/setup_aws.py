# ============================================================
#  movie Magic — Complete AWS Setup Script
#  File: setup_aws.py
#
#  Run this ONCE after filling your .env file.
#  It will automatically:
#    1. Create DynamoDB table:movie Magictix_users
#    2. Create DynamoDB table:movie Magic_bookings (with 2 GSIs)
#    3. Create SNS topic:movie MagicTixBookings
#    4. Subscribe your email to SNS topic
#    5. Create IAM Role: moviemagicTixEC2Role (DynamoDB + SNS access)
#    6. Launch EC2 instance (Ubuntu 22.04, t2.micro Free Tier)
#
#  Usage:
#    python setup_aws.py
# ============================================================

import boto3, json, time, os
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "ap-south-1")
KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")
TOKEN  = os.getenv("AWS_SESSION_TOKEN") or None

def kw():
    d = dict(region_name=REGION, aws_access_key_id=KEY_ID, aws_secret_access_key=SECRET)
    if TOKEN: d["aws_session_token"] = TOKEN
    return d

dynamodb = boto3.client("dynamodb", **kw())
sns      = boto3.client("sns",      **kw())
iam      = boto3.client("iam",      **kw())
ec2      = boto3.client("ec2",      **kw())

print("\n" + "="*58)
print("  Movie Magic — Full AWS Setup")
print("="*58)


# ════════════════════════════════════════════════════════════
#  STEP 1 — DynamoDB: Movie Magic_users
#  Primary Key: email (String)
#  Stores: name, email, hashed password, mobile, city, login_count
# ════════════════════════════════════════════════════════════
print("\n[1/6] Creating DynamoDB table: Movie Magic_users ...")
try:
    dynamodb.create_table(
        TableName            = "Movie Magic_users",
        KeySchema            = [{"AttributeName": "email", "KeyType": "HASH"}],
        AttributeDefinitions = [{"AttributeName": "email", "AttributeType": "S"}],
        BillingMode          = "PAY_PER_REQUEST"
    )
    print("      [+] Movie Magic_users created successfully.")
except dynamodb.exceptions.ResourceInUseException:
    print("      [!] Movie Magic_users already exists — skipped.")
except Exception as e:
    print(f"      [X] Error: {e}")


# ════════════════════════════════════════════════════════════
#  STEP 2 — DynamoDB: Movie Magic_bookings
#  Primary Key: booking_id (String)
#  GSI 1: user-email-index — query all bookings by a user
#  GSI 2: seat-index       — query occupied seats for a show
#  show_key format: movieId#theater#date#time
# ════════════════════════════════════════════════════════════
print("\n[2/6] Creating DynamoDB table: Movie Magic_bookings ...")
try:
    dynamodb.create_table(
        TableName            = "Movie Magic_bookings",
        KeySchema            = [{"AttributeName": "booking_id", "KeyType": "HASH"}],
        AttributeDefinitions = [
            {"AttributeName": "booking_id", "AttributeType": "S"},
            {"AttributeName": "user_email",  "AttributeType": "S"},
            {"AttributeName": "show_key",    "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes = [
            {
                "IndexName": "user-email-index",
                "KeySchema": [{"AttributeName": "user_email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "seat-index",
                "KeySchema": [{"AttributeName": "show_key", "KeyType": "HASH"}],
                "Projection": {
                    "ProjectionType":   "INCLUDE",
                    "NonKeyAttributes": ["seats"]
                }
            }
        ],
        BillingMode = "PAY_PER_REQUEST"
    )
    print("      [+] Movie Magic_bookings created.")
    print("      [+] GSI user-email-index created.")
    print("      [+] GSI seat-index created.")
except dynamodb.exceptions.ResourceInUseException:
    print("      [!] Movie Magic_bookings already exists — skipped.")
except Exception as e:
    print(f"      [X] Error: {e}")


# ════════════════════════════════════════════════════════════
#  STEP 3 — SNS: Create Topic
#  All booking confirmations are published to this topic.
#  Every subscribed email receives the confirmation.
# ════════════════════════════════════════════════════════════
print("\n[3/6] Creating SNS topic: Movie MagicBookings ...")
topic_arn = None
try:
    resp      = sns.create_topic(Name="Movie MagicBookings")
    topic_arn = resp["TopicArn"]
    print(f"      [+] SNS topic created.")
    print(f"\n      IMPORTANT — Copy this into your .env file:")
    print(f"      SNS_TOPIC_ARN={topic_arn}\n")
except Exception as e:
    print(f"      [X] Error: {e}")


# ════════════════════════════════════════════════════════════
#  STEP 4 — SNS: Subscribe Email
#  Check your inbox and click "Confirm subscription"
# ════════════════════════════════════════════════════════════
print("[4/6] Subscribing your email to SNS topic ...")
if topic_arn:
    admin_email = input("      Enter email to receive booking confirmations: ").strip()
    if admin_email:
        try:
            sns.subscribe(TopicArn=topic_arn, Protocol="email", Endpoint=admin_email)
            print(f"      [+] Subscription sent to: {admin_email}")
            print(f"      [!] Open your email and click 'Confirm subscription'.")
        except Exception as e:
            print(f"      [X] Error: {e}")
    else:
        print("      [!] No email entered — skipped.")
else:
    print("      [!] SNS topic unavailable — skipped.")


# ════════════════════════════════════════════════════════════
#  STEP 5 — IAM Role: Movie MagicEC2Role
#
#  Why needed?
#    When your Flask app runs on EC2, it needs permission to
#    read/write DynamoDB and publish to SNS.
#    Instead of putting credentials in the code (unsafe),
#    we attach an IAM role to the EC2 instance.
#    The role automatically grants the permissions.
#
#  Policies attached:
#    - AmazonDynamoDBFullAccess
#    - AmazonSNSFullAccess
# ════════════════════════════════════════════════════════════
print("\n[5/6] Creating IAM Role: Movie MagicEC2Role ...")

# Trust policy: allows EC2 service to assume this role
trust_policy = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect":    "Allow",
        "Principal": {"Service": "ec2.amazonaws.com"},
        "Action":    "sts:AssumeRole"
    }]
})

role_arn = None
try:
    resp     = iam.create_role(
        RoleName                 = "Movie MagicEC2Role",
        AssumeRolePolicyDocument = trust_policy,
        Description              = "IAM role for Movie Magic EC2 — grants DynamoDB and SNS access"
    )
    role_arn = resp["Role"]["Arn"]
    print(f"      [+] IAM Role created: Movie MagicEC2Role")
    print(f"      [+] Role ARN: {role_arn}")

    # Attach AWS managed policies
    for policy_arn in [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonSNSFullAccess",
    ]:
        iam.attach_role_policy(RoleName="Movie MagicEC2Role", PolicyArn=policy_arn)
        print(f"      [+] Policy attached: {policy_arn.split('/')[-1]}")

    # Create instance profile (needed to attach role to EC2)
    try:
        iam.create_instance_profile(InstanceProfileName="Movie MagicEC2Profile")
        print("      [+] Instance profile created: Movie MagicEC2Profile")
    except iam.exceptions.EntityAlreadyExistsException:
        print("      [!] Instance profile already exists — skipped.")

    # Link role to instance profile
    try:
        iam.add_role_to_instance_profile(
            InstanceProfileName = "Movie MagicEC2Profile",
            RoleName            = "Movie MagicEC2Role"
        )
        print("      [+] Role linked to instance profile.")
    except iam.exceptions.LimitExceededException:
        print("      [!] Role already linked — skipped.")

except iam.exceptions.EntityAlreadyExistsException:
    print("      [!] Movie MagicEC2Role already exists — skipped.")
    try:
        role_arn = iam.get_role(RoleName="Movie MagicEC2Role")["Role"]["Arn"]
        print(f"      [+] Found existing role: {role_arn}")
    except: pass
except Exception as e:
    print(f"      [X] IAM error: {e}")


# ════════════════════════════════════════════════════════════
#  STEP 6 — EC2: Create Security Group + Launch Instance
#
#  Security Group opens:
#    - Port 22   → SSH (to connect and manage server)
#    - Port 80   → HTTP (standard web access)
#    - Port 5000 → Flask app
#
#  EC2 Instance:
#    - Ubuntu 22.04 LTS
#    - t2.micro (Free Tier eligible)
#    - IAM Role attached (no credentials needed on server)
#    - User data script auto-installs Python + packages
# ════════════════════════════════════════════════════════════
print("\n[6/6] Setting up EC2 instance ...")

do_launch = input("      Launch EC2 instance now? (yes/no): ").strip().lower()

if do_launch == "yes":

    # ── Create Security Group ────────────────────────────────
    sg_id = None
    try:
        sg    = ec2.create_security_group(
            GroupName   = "Movie MagicSG",
            Description = "Movie Magic Flask server — ports 22, 80, 5000"
        )
        sg_id = sg["GroupId"]
        print(f"      [+] Security group created: {sg_id}")

        ec2.authorize_security_group_ingress(
            GroupId       = sg_id,
            IpPermissions = [
                {"IpProtocol":"tcp","FromPort":22,  "ToPort":22,  "IpRanges":[{"CidrIp":"0.0.0.0/0"}]},
                {"IpProtocol":"tcp","FromPort":80,  "ToPort":80,  "IpRanges":[{"CidrIp":"0.0.0.0/0"}]},
                {"IpProtocol":"tcp","FromPort":5000,"ToPort":5000,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]},
            ]
        )
        print("      [+] Ports 22, 80, 5000 opened.")
    except ec2.exceptions.ClientError as e:
        if "InvalidGroup.Duplicate" in str(e):
            sg_id = ec2.describe_security_groups(
                GroupNames=["Movie MagicSG"])["SecurityGroups"][0]["GroupId"]
            print(f"      [!] Security group already exists: {sg_id}")
        else:
            print(f"      [X] Security group error: {e}")

    # ── User Data: runs automatically when EC2 boots ─────────
    # This installs Python, pip, venv and all packages
    user_data_script = """#!/bin/bash
set -e
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git

# Setup project directory
mkdir -p /home/ubuntu/moviemagic
cd /home/ubuntu/moviemagic

# Create and activate virtualenv
python3 -m venv venv
source venv/bin/activate

# Install all required packages
pip install flask==3.0.3 werkzeug==3.0.3 boto3==1.34.144 python-dotenv==1.0.1 gunicorn==22.0.0

# Write startup instructions
cat > /home/ubuntu/README.txt << 'EOF'
Movie Magic EC2 Setup Complete!

STEPS TO GO LIVE:
1. Upload project files from your local machine:
   scp -i your-key.pem -r Movie Magic_final/* ubuntu@<this-ip>:~/Movie Magic/

2. Upload your .env file:
   scp -i your-key.pem .env ubuntu@<this-ip>:~/Movie Magic/

3. SSH into this server:
   ssh -i your-key.pem ubuntu@<this-ip>

4. Run the app:
   cd ~/Movie Magic
   source venv/bin/activate
   python app.py

5. Open in browser:
   http://<this-ip>:5000

FOR PRODUCTION (always running):
   nohup gunicorn -w 4 -b 0.0.0.0:5000 app:app &
EOF

chown ubuntu:ubuntu /home/ubuntu/README.txt
chown -R ubuntu:ubuntu /home/ubuntu/moviemagic
echo "Movie Magic EC2 setup done." >> /var/log/moviemagic-setup.log
"""

    # ── Launch EC2 Instance ──────────────────────────────────
    try:
        print("      [~] Waiting 12 seconds for IAM profile to propagate ...")
        time.sleep(12)

        params = {
            "ImageId":      "ami-0f58b397bc5c1f2e8",   # Ubuntu 22.04 LTS — ap-south-1
            "InstanceType": "t2.micro",                  # Free Tier
            "MinCount":     1,
            "MaxCount":     1,
            "UserData":     user_data_script,
            "TagSpecifications": [{
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "Movie Magic-Server"}]
            }]
        }

        if sg_id:
            params["SecurityGroupIds"] = [sg_id]
        if role_arn:
            params["IamInstanceProfile"] = {"Name": "Movie MagicEC2Profile"}

        resp     = ec2.run_instances(**params)
        inst     = resp["Instances"][0]
        inst_id  = inst["InstanceId"]

        print(f"\n      [+] EC2 instance launched!")
        print(f"      [+] Instance ID: {inst_id}")
        print(f"      [+] IAM Role attached: Movie MagicEC2Role")
        print(f"      [~] Instance is starting... (takes 1-2 minutes)")
        print(f"""
      TO FIND YOUR PUBLIC IP:
        AWS Console → EC2 → Instances → {inst_id}
        OR run: aws ec2 describe-instances \\
                  --instance-ids {inst_id} \\
                  --query 'Reservations[0].Instances[0].PublicIpAddress'

      THEN UPLOAD YOUR CODE:
        scp -i your-key.pem -r Movie Magic_final/ ubuntu@<PUBLIC-IP>:~/
        scp -i your-key.pem .env ubuntu@<PUBLIC-IP>:~/Movie Magic/

      THEN SSH IN AND RUN:
        ssh -i your-key.pem ubuntu@<PUBLIC-IP>
        cd Movie Magic && source venv/bin/activate && python app.py

      OPEN IN BROWSER:
        http://<PUBLIC-IP>:5000
""")
    except Exception as e:
        print(f"      [X] EC2 launch error: {e}")

else:
    print("      [!] EC2 launch skipped.")
    print("      [!] When you launch EC2 manually, attach IAM role: Movie MagicEC2Role")


# ════════════════════════════════════════════════════════════
#  COMPLETE SUMMARY
# ════════════════════════════════════════════════════════════
print("\n" + "="*58)
print("  AWS Setup Summary")
print("="*58)
print("""
  AWS Service         Status
  ─────────────────────────────────────────────────────
  DynamoDB Users      moviemagic_users (email PK)
  DynamoDB Bookings   moviemagic_bookings (2 GSIs)
  SNS Topic           Movie MagicBookings
  IAM Role            Movie MagicEC2Role
    Policies:           AmazonDynamoDBFullAccess
                        AmazonSNSFullAccess
  EC2 Instance        Movie Magic-Server (Ubuntu 22.04)
    Security Group:     Port 22, 80, 5000 open

  ── SESSION MANAGEMENT (handled inside app.py) ──────
  Flask server-side sessions with SECRET_KEY encryption.
  login_required decorator protects all booking routes.
  Session stores: user_email, user_name, user_city,
                  login_count, booking_draft, last_booking.

  ── NEXT STEPS ──────────────────────────────────────
  1. Copy SNS_TOPIC_ARN printed above into .env
  2. Click 'Confirm subscription' in your email
  3. Upload code to EC2 and run python app.py
  4. Open http://<EC2-PUBLIC-IP>:5000
""")
