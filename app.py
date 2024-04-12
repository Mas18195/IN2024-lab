from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import bcrypt
import string
import secrets
import requests
import os
from transformers import pipeline
from datetime import datetime
import math

app = Flask(__name__)

# Configuration
app.secret_key = os.urandom(24) # Generated random Secret key to provide security
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload directory exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Function to establish user database connection
def dbConnectionUser():
    con = sqlite3.connect("users.db")
    return con

# Function to establish reports database connection
def dbConnectionReport():
    con = sqlite3.connect("reports.db")

    # Create custom SQL functions
    con.create_function("SQRT", 1, math.sqrt)
    con.create_function("COS", 1, math.cos)
    con.create_function("SIN", 1, math.sin)
    con.create_function("ASIN", 1, math.asin)
    con.create_function("RADIANS", 1, math.radians)

    return con

# Function to generate a random API KEY
def generate_api_key():
    alphabet = string.ascii_letters + string.digits # Creates a string using lower/upper case letters and numbers
    api_key = ''.join(secrets.choice(alphabet) for i in range(32))  # Generate a 32-character random string
    return api_key

# Function to generate password hash
def generate_password_hash(password):
    password = bytes(password, 'utf-8') # Convert password to bytes
    salt = bcrypt.gensalt() # Generate a salt
    hashed_password = bcrypt.hashpw(password, salt) # Hash the password
    return hashed_password

# Function to get state and country from GPS coordinates
def get_location_data(lat, long):
    url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={long}&localityLanguage=en"
    response = requests.get(url) # Get response
    data = response.json() # Decode JSON response
    state = data.get("principalSubdivision") # Get state name
    country = data.get("countryName") # Get country name
    
    return state, country

# Function to get weather data
def get_weather(lat, long):
    host = "https://api.open-meteo.com"
    resource = "/v1/forecast"
    params = {
        "latitude": lat, # Extracting latitude from Dataframe
        "longitude": long,  # Extracting longitude from Dataframe
    	"current": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "past_days":0
    }
    res = requests.get(host+resource, params=params) # Get response
    data = res.json() # Decode JSON response
    temperature = str(data['current']['temperature_2m']) + data['current_units']['temperature_2m'] # Get temperature and unit
    
    return temperature

# Function to give sentiment analysis to description
def sentiment_analysis(text):
    # Load pre-trained sentiment analysis model
    sentiment_classifier = pipeline("text-classification", model="distilbert-base-uncased-finetuned-sst-2-english")
    result = sentiment_classifier(text) # Analyze sentiment of the text
    label = result[0]['label'] # Extract sentiment label

    return label

# Function query various parameters using HTML Table
def query_reports(start_date=None, end_date=None, lat=None, long=None, dist=None, max_reports=None, sort=None):
    con = dbConnectionReport() # Connect to databse
    c = con.cursor() # Creates cursor object

    query = "SELECT * FROM Reports WHERE 1=1" # Initalize SQL query string using SELECT

    # Parameters to sort by when provided
    if start_date:
        query += f" AND datetime_entry >= '{start_date}'" # Filter record after start date
    if end_date:
        query += f" AND datetime_entry <= '{end_date}'" # Filter record before start date
    if lat and long and dist:
        # Calculate the distance using Haversine formula and if it is less or equal to the inputted distance
        query += f" AND (6371 * 2 * ASIN(SQRT(SIN(RADIANS(({lat} - latitude) / 2) * SIN(RADIANS(({lat} - latitude) / 2)) + COS(RADIANS({lat})) * COS(RADIANS(latitude)) * SIN(RADIANS(({long} - longitude) / 2)) * SIN(RADIANS(({long} - longitude) / 2)))))) <= {dist}"
    if sort:
        query += f" ORDER BY datetime_entry {'ASC' if sort == 'newest' else 'DESC'}" # Order by datetime
    if max_reports:
        query += f" LIMIT {max_reports}" # Limit the number of records to inputted value

    c.execute(query) # Executes constructed SQL query
    reports = c.fetchall() # Fetches all the resulting records
    con.close() # Closes connection to database

    return reports


# Home route
@app.route('/', methods=['GET', 'POST'])
def home():
    register_error = None  # Initialize register error message variable
    login_error = None  # Initialize login error message variable
    registered = None # Initialize registered message variable
    if request.method == 'POST':

        if 'register' in request.form:
            username = request.form['username'] # Retrive entered username
            password = request.form['password'] # Retrive entered password
            hashed_password = generate_password_hash(password) # Using function to has password
            api_key = generate_api_key() # Using function to generate API KEY

            with dbConnectionUser() as con:
                # Attempts to register the user. If the username is already taken then the user is notified.
                try:
                    # Creates new user to table based on inputed values
                    con.execute("INSERT INTO Users (username, password_hash, api_key) VALUES (?, ?, ?)", (username, hashed_password, api_key))
                    registered = "You are now registered! Please Login."
                except sqlite3.IntegrityError: # Catches the error rather than crashing program
                    register_error = "Username already exists. Please choose a different username."
        
        elif 'login' in request.form:
            username = request.form['username']
            password = request.form['password']

            with dbConnectionUser() as con:
                # Excute SQL querry to retrive password for username
                cursor = con.cursor()
                cursor.execute("SELECT password_hash FROM Users WHERE username=?", (username,))
                user_password = cursor.fetchone()
                
                # Checks if user_password exists in the database and if it matches the users password
                if user_password and bcrypt.checkpw(password.encode('utf-8'), user_password[0]):
                    session['username'] = username # Sets the username for the session
                    return redirect('/username') # Redirct user to username page
                else:
                    login_error = "Invalid username or password" # Tells user provided information is wrong

    # Renders home.html page and passes these variables to the page
    return render_template('home.html', registered=registered, register_error=register_error, login_error=login_error)

# Logout route
@app.route('/logout')
def logout():
    session.pop('username', None) # Removes 'username' key from session to log out user
    session.pop('api_key', None) # Removes 'api_key' from session to log out user
    return redirect('/') # Redirect root/home url

# Username route
@app.route('/username', methods=['GET', 'POST'])
def username():
    # Checks if username is stored in session indicating user is logged in
    if 'username' in session: 

        # When user POSTS information, it checks that there is an API KEY
        if request.method == 'POST': 
            api_key = request.form.get('api_key') # Get API KEY from the HTML form

            # Checks if API KEY from the HTML form matches the API KEY stored in the session from the user.
            if api_key != session.get('api_key'): 
                return redirect('/logout') # User is logged out

            return redirect('/report') # Goes to report page if API KEY matches

        # Gets User API_KEY and stores it in the session
        with dbConnectionUser() as con:
            cursor = con.cursor()
            cursor.execute("SELECT api_key FROM Users WHERE username=?", (session['username'],))
            api_key = cursor.fetchone()[0]
            session['api_key'] = api_key
            return render_template('username.html', api_key=api_key)
        
    else: # If a user is not in session redirect to root/home
        return redirect('/')
    
# Report route
@app.route('/report', methods=['POST']) # Accepts only POST method
def report():
    if request.method == 'POST': # Checks if the method is POST
        
        # Get username and user_id from API key used to POST
        with dbConnectionUser() as con:
            cursor = con.cursor()
            api_key = request.form['api_key']
            cursor.execute("SELECT user_id, username FROM Users WHERE api_key=?", (api_key,))
            row = cursor.fetchone()
            user_id, username = row

        datetime_entry = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Get data/time of submission

        lat = request.form['latitude'] # Get latitude from HTML form
        long = request.form['longitude'] # Get longitude from HTML form

        state, country = get_location_data(lat, long) # Using function to get state and country

        temp = get_weather(lat, long) # Using function get current temperature in area

        submitter_ip = request.remote_addr # Get submitter's IP address

        description = request.form["description"] # Get description from HTML form

        sentiment = sentiment_analysis(description) # Using function to give sentiment classification of description

        file = request.files['file'] # Get name of uploaded path
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename) # Get saved path of file

        # Save data to report database
        with dbConnectionReport() as con:
            # Insert data into the Reports table
            con.execute("""
                INSERT INTO Reports (user_id, username, datetime_entry, latitude, longitude, state, country, 
                temperature, ip_address,  description, classification, file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, datetime_entry, lat, long, state, country, temp, submitter_ip, 
                  description, sentiment, file_path))
            
        # Renders report.html page and passes these variables to the page
        return render_template("report.html", user_id=user_id, username=username, datetime_entry=datetime_entry, 
                               lat=lat, long=long, state=state, country=country, temp=temp, submitter_ip=submitter_ip,
                               description=description, sentiment=sentiment, file_path=file_path)
    
    else: # If method is prohibited, throw up a webpage saying method is not allowed 
        return "Method Not Allowed", 405 

@app.route('/data', methods=['GET'])
def get_data():
    if request.method == 'GET': # Checks if the method is GET

        # These extracts the filter query parameters to append to the URL 
        start_date = request.args.get('start_date') 
        end_date = request.args.get('end_date')
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        dist = request.args.get('dist', type=float)
        max_reports = request.args.get('max', type=int)
        sort = request.args.get('sort')

        # Using function to get query parameters
        reports = query_reports(start_date, end_date, lat, lng, dist, max_reports, sort)

        # Renders data.html page and passes these variables to the page
        return render_template('data.html', reports=reports)

    else:
          return "Method Not Allowed", 405  


if __name__ == '__main__':
    app.run(debug=False,  port=5000)