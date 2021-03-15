import json
import logging

import boto3
from boto3.dynamodb.conditions import Attr

import jwt

# Setting up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setting up dyanmodb
dynamodb = boto3.resource('dynamodb')
speech_analysis_table = dynamodb.Table('speech_analysis')

#  Setting up AWS s3
s3 = boto3.client('s3')


def lambda_handler(event, context):
    try:
        user_id = get_user_id_from_auth_token(event)
        results = get_speech_analysis_results(user_id)
        return {
            'statusCode': 200,
            'body': json.dumps(results)
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps('Something went wrong: ' + str(e))
        }


def get_user_id_from_auth_token(event):
    bearer_token = event['headers']['authorization']
    # we remove the "Bearer " prefix so that jwt can process the token
    token = bearer_token.replace('Bearer ', '')
    decoded = jwt.decode(token, options={"verify_signature": False})
    user_id = decoded["cognito:username"]
    return user_id


def get_speech_analysis_results(user_id):
    # Inefficient way of filtering
    # When using scan, ALL the records are first retrieved and then sorted. This method will not scale
    response = speech_analysis_table.scan(FilterExpression=Attr('user_id').eq(user_id))
    return response['Items']
