#!/bin/bash

cd /app/flask_app

# Install dependencies if needed
pip install -r requirements.txt > /dev/null 2>&1

# Create instance directory
mkdir -p instance

# Run Flask app
python app.py
