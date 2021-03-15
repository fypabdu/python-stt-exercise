import boto3
import uuid
import json
import requests
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)

import json

def main():

    # f = open("demofile2.txt", "w+")
    # f.write("Ayyyyy")
    # f.close()

    response = requests.get('https://4tb8nifz6a.execute-api.us-east-1.amazonaws.com/speech/uploadurl?file_name=sample-0&user=abuuu')
    data = response.json()
    
    print(data)
    
    f = open("./sample-0.mp3", "rb")
    response = requests.post(url=data['url'], data=data['fields'],
                         files={'file': f})
    f.close()
    
    
    
    print("Hello World!")

if __name__ == "__main__":
    main()
