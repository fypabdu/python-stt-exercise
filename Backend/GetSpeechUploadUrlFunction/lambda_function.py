import json
import logging
import uuid

import boto3

import jwt

# Setting up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setting up AWS S3 client
s3 = boto3.client('s3')


def lambda_handler(event, context):
    try:
        presigned_post = get_presigned_url(event)
        return {
            'statusCode': 200,
            'body': json.dumps(presigned_post)
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps('Something went wrong: ' + str(e))
        }


def get_presigned_url(event):
    user_id = get_user_id_from_auth_token(event)
    file_name = event['queryStringParameters']['file_name']
    s3_object_key = generate_unique_audio_file_name(file_name)

    presigned_post = s3.generate_presigned_post(
        Bucket='com.abu.stt',
        Key=s3_object_key,
        ExpiresIn=3600,
        Fields={'x-amz-meta-file_name': file_name, 'x-amz-meta-user': user_id},
        Conditions=[{'x-amz-meta-file_name': file_name}, {'x-amz-meta-user': user_id}]
    )
    return presigned_post


def get_user_id_from_auth_token(event):
    bearer_token = event['headers']['authorization']
    # we remove the "Bearer " prefix so that jwt can process the token
    token = bearer_token.replace('Bearer ', '')
    decoded = jwt.decode(token, options={"verify_signature": False})
    user_id = decoded["cognito:username"]
    return user_id


def generate_unique_audio_file_name(file_name):
    return file_name + '_' + str(uuid.uuid4()) + '.mp3'
