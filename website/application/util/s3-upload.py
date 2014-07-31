#!/usr/bin/env python

from base64 import b64encode
from datetime import datetime, timedelta
from json import dumps
from os import environ
from uuid import uuid4
import hmac
import sha

from flask import Flask, render_template, jsonify

app = Flask(__name__)
for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_S3_BUCKET_URL'):
    app.config[key] = environ[key]

@app.route('/')
def index():
    return render_template('s3-upload.html')

@app.route('/params')
def params():
    def make_policy():
        policy_object = {
            "expiration": (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "conditions": [
                { "bucket": "hackmit-test" },
                { "acl": "private" },
                ["starts-with", "$key", "uploads/"],
                { "success_action_status": "201" },
                ["content-length-range", "0", "104857600"],
            ]
        }
        return b64encode(dumps(policy_object).replace('\n', '').replace('\r', ''))

    def sign_policy(policy):
        return b64encode(hmac.new(app.config['AWS_SECRET_ACCESS_KEY'], policy, sha).digest())

    policy = make_policy()
    return jsonify({
        "policy": policy,
        "signature": sign_policy(policy),
        "key": "uploads/" + 'testanudevelop'+ ".bin",
        "success_action_redirect": "/"
    })


if __name__ == '__main__':
    app.run(debug=True)
