import boto3
import os

def get_s3_client():
    return boto3.client('s3', 
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION', 'us-east-1')
    )

def upload_to_s3(file_path, bucket, object_name):
    client = get_s3_client()
    client.upload_file(file_path, bucket, object_name)
