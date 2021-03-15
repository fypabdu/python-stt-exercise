import sys
import logging.handlers
import json

from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from flask import Flask, render_template_string, session, redirect, request, url_for, render_template
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, validators

import flask_login
from jose import jwt

import config

application = Flask(__name__)
application.secret_key = config.FLASK_SECRET

login_manager = flask_login.LoginManager()
login_manager.init_app(application)

# loading and caching the cognito JSON Web Key (JWK)
# https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html
JWKS_URL = ("https://cognito-idp.%s.amazonaws.com/%s/.well-known/jwks.json"
            % (config.AWS_REGION, config.COGNITO_POOL_ID))
JWKS = requests.get(JWKS_URL).json()["keys"]

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Handler
LOG_FILE = '/tmp/sample-app.log'
handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1048576, backupCount=5)
handler.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add Formatter to Handler
handler.setFormatter(formatter)

# add Handler to Logger
logger.addHandler(handler)

if __name__ == '__main__':
    application.debug = True
    application.run()
    logger.info('App Started')
    application.config['ENV'] = 'development'
    application.config['DEBUG'] = True
    application.config['TESTING'] = True


class User(flask_login.UserMixin):
    # Standard flask_login UserMixin
    pass


@login_manager.user_loader
def user_loader(session_token):
    # Populating the user object and checking session expiry
    if "expires" not in session:
        return None

    expires = datetime.utcfromtimestamp(session['expires'])
    expires_seconds = (expires - datetime.utcnow()).total_seconds()
    if expires_seconds < 0:
        return None

    user = User()
    user.id = session_token
    user.name = session['name']
    return user


@application.route("/")
def home():
    return render_template('home.html')


@application.route("/login")
def login():
    # http://docs.aws.amazon.com/cognito/latest/developerguide/login-endpoint.html
    # Need to handle CSRF
    cognito_login = ("https://%s/"
                     "login?response_type=code&client_id=%s"
                     "&redirect_uri=%s/callback" %
                     (config.COGNITO_DOMAIN, config.COGNITO_CLIENT_ID, config.BASE_URL))
    return redirect(cognito_login)


@application.route("/callback")
def callback():
    # Exchanging the auth code for Cognito ID and Access tokens (JWT)
    # http://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html
    code = request.args.get('code')
    request_parameters = {'grant_type': 'authorization_code',
                          'client_id': config.COGNITO_CLIENT_ID,
                          'code': code,
                          "redirect_uri": config.BASE_URL + "/callback"}
    response = requests.post("https://%s/oauth2/token" % config.COGNITO_DOMAIN,
                             data=request_parameters,
                             auth=HTTPBasicAuth(config.COGNITO_CLIENT_ID,
                                                config.COGNITO_CLIENT_SECRET))

    # http://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html
    if response.status_code == requests.codes.ok:
        verify_token(response.json()["access_token"])
        id_token = verify_token(response.json()["id_token"], response.json()["access_token"])

        user = User()
        user.id = id_token["cognito:username"]

        # Storing the raw id token also since it can then be used to
        # make authenticated backend API calls (through API gateway)
        session['raw_id_token'] = response.json()["id_token"]
        session['name'] = id_token["name"]
        session['user_id'] = id_token["cognito:username"]
        session['expires'] = id_token["exp"]
        session['refresh_token'] = response.json()["refresh_token"]

        flask_login.login_user(user, remember=True)
        return redirect(url_for("home"))

    return render_template_string("""
        {% extends "main.html" %}
        {% block content %}
            <p>Something went wrong</p>
        {% endblock %}""")


def verify_token(token, access_token=None):
    # Verifying the cognito access and ID tokens
    # getting the key id from the header, locating it in the cognito keys
    # and verifying the key
    header = jwt.get_unverified_header(token)
    key = [k for k in JWKS if k["kid"] == header['kid']][0]
    id_token = jwt.decode(token, key, audience=config.COGNITO_CLIENT_ID, access_token=access_token)
    return id_token


@application.route("/logout")
def logout():
    # http://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html
    flask_login.logout_user()
    session.clear()
    cognito_logout = ("https://%s/"
                      "logout?response_type=code&client_id=%s"
                      "&logout_uri=%s/" %
                      (config.COGNITO_DOMAIN, config.COGNITO_CLIENT_ID, config.BASE_URL))
    return redirect(cognito_logout)


@application.errorhandler(401)
def unauthorized(exception):
    return render_template_string("""
        {% extends "main.html" %}
        {% block content %}
            <p>Please login to access this page</p>
        {% endblock %}"""), 401


class SpeechUploadForm(FlaskForm):
    # File upload form using flask_wtf
    audio = FileField('audio', validators=[
        FileRequired(),
        FileAllowed(['mp3', 'Only files of .mp3 are allowed!'])
    ])
    file_name = StringField(u'File Name', validators=[
        validators.required(message="Please enter a file name for your reference"),
        validators.Regexp('^\w+$', message="File name must contain only letters, numbers or underscore")])


@application.route("/speechanalysis", methods=('GET', 'POST'))
@flask_login.login_required
def speech_analysis():
    speech_upload_form = SpeechUploadForm()
    speech_analysis_results = get_speech_analysis_results()

    if request.method == 'POST' and request.form['form_name'] == 'upload_form':
        if speech_upload_form.validate_on_submit():
            logger.info("analysis form submitted")

            audio_file = speech_upload_form.audio.data
            file_name = speech_upload_form.file_name.data
            logger.info("File Name: {}".format(file_name))

            upload_audio_file(audio_file, file_name)

    return render_template('speech_analysis.html',
                           upload_form=speech_upload_form,
                           speech_analysis_results=speech_analysis_results)


def upload_audio_file(audio_file, file_name):
    # Getting a presigned url for a location to upload the speech audio file
    endpoint = config.API_GW_URL + '/speech/uploadurl?file_name=' + file_name
    headers = {'Authorization': 'Bearer ' + session['raw_id_token']}
    response = requests.get(url=endpoint, headers=headers)
    data = response.json()

    # Posting/uploading the speech file to the provided url
    requests.post(url=data['url'], data=data['fields'], files={'file': audio_file})

def get_speech_analysis_results():
    endpoint = config.API_GW_URL + '/speech/analysis'
    headers = {'Authorization': 'Bearer ' + session['raw_id_token']}
    speech_analysis_results = requests.get(endpoint, headers=headers).json()

    # In order for json tree viewer to be able to parse the transcription, we call json.dumps on all
    # the transcription results
    speech_analysis_results_jsonified = []
    for speech_analysis in speech_analysis_results:
        speech_analysis['result'] = json.dumps(speech_analysis['result'])
        speech_analysis_results_jsonified.append(speech_analysis)

    return speech_analysis_results_jsonified
