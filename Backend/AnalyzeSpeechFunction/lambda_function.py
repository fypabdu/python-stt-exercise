import json
import logging
import time

import boto3

import requests

# Setting up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Setting up dyanmodb
dynamodb = boto3.resource('dynamodb')
speech_analysis_table = dynamodb.Table('speech_analysis')

#  Setting up AWS s3
s3 = boto3.client('s3')

# Setting up Amazon Transcribe
transcribe = boto3.client('transcribe')


class SpeechAnalysis:
    def __init__(self, id, file_name, file_url, user_id, status='', result=''):
        self.id = id
        self.file_name = file_name
        self.file_url = file_url
        self.user_id = user_id
        self.status = status
        self.result = result


def lambda_handler(event, context):
    try:
        analyze_speech(event)
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps('Something went wrong: ' + str(e))
        }

    return {
        'statusCode': 200,
        'body': json.dumps('File accepted for processing')
    }


def analyze_speech(event):
    for record in event['Records']:
        metadata = extract_s3_file_metadata(record)
        logger.info('Processing file: {}'.format(metadata))

        # The link between the file (S3 object) and the user uploading it is made through the S3 object metadata.
        # Hence we retrieve those details here.
        user_id = metadata['Metadata']['user']
        original_file_name = metadata['Metadata']['file_name']

        bucket, key = get_bucket_details(record)
        speech_file_uri = 'https://s3.amazonaws.com/' + bucket + '/' + key

        speech_analysis = SpeechAnalysis(id=key, file_name=original_file_name, file_url=speech_file_uri,
                                         user_id=user_id)
        update_analysis_status(speech_analysis, 'Transcribing')

        transcription_job_result = perform_transcription_job(speech_file_uri, key)
        logger.info("Transcription Job Result {}".format(transcription_job_result))
        update_analysis_status(speech_analysis, 'Transcribed')

        transcription = get_transcription(transcription_job_result)
        logger.info("Transcription {}".format(transcription))

        speech_analysis.result = transcription
        update_analysis_status(speech_analysis, 'Complete')


def extract_s3_file_metadata(record):
    bucket, key = get_bucket_details(record)

    logger.info("Bucket Name: {}".format(bucket))
    logger.info("Key/Object name:{}".format(key))

    response = s3.head_object(Bucket=bucket, Key=key)
    return response


def get_bucket_details(record):
    bucket = record['s3']['bucket']['name']
    key = record['s3']['object']['key']
    return bucket, key


def perform_transcription_job(speech_file_uri, speech_file_id):
    transcribe.start_transcription_job(
        TranscriptionJobName=speech_file_id,
        Media={'MediaFileUri': speech_file_uri},
        MediaFormat='mp3',
        LanguageCode='en-US'
    )

    # Amazon Transcribe jobs are asynchronous, in this naive implementation  we pause the thread until
    # the job has completed (or failed) so that we can go on to read the transcription result.
    # Be sure to set a large enough timeout value when deploying this code to Lambda.
    while True:
        status = transcribe.get_transcription_job(TranscriptionJobName=speech_file_id)
        if status['TranscriptionJob']['TranscriptionJobStatus'] in ['COMPLETED', 'FAILED']:
            break
        logger.info("Waiting for transcription job to complete...")
        time.sleep(5)

    return status


def get_transcription(transcription_job_result):
    # Transcription results are provided as a S3 uri, hence we need to make another request to get the actual
    # transcription or result
    transcription_url = transcription_job_result['TranscriptionJob']['Transcript']['TranscriptFileUri']
    response = requests.get(transcription_url, allow_redirects=True)
    return response.json()


def update_analysis_status(speech_analysis, status):
    speech_analysis.status = status
    persist_speech_analysis(speech_analysis)


def persist_speech_analysis(speech_analysis):
    # __dict__ is called to convert the object to a dictionary since that is what dynamodb (sdk) requires
    speech_analysis_table.put_item(Item=speech_analysis.__dict__)
