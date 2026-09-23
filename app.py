# 'request' lets us capture submitted forms and files
# 'flash' lets us send temporary success/error messages to the HTML
# 'redirect' and 'url_for' let us bounce the user to another page after they upload
from flask import Flask, render_template, request, flash, redirect, url_for

# Initialize the Flask web application
app = Flask(__name__)

# A secret key is required by Flask to use 'flash' messages securely
app.secret_key = "super_secret_capstone_key"


# Route 1: The Home/Search Page
@app.route("/")
def index():
    # Ejlin will eventually replace this mock list with an actual database query.
    # For now, we create a fake list of dictionaries so your front-end Jinja loop has data to render.
    mock_facilities = [
        {"id": 1353, "name": "Ghent Generating Station", "state": "KY", "fuel": "Coal", "co2": "8,450,120"},
        {"id": 1384, "name": "Trimble County Generating Station", "state": "KY", "fuel": "Natural Gas", "co2": "3,120,400"}
    ]
    
    # We pass the 'mock_facilities' list into the HTML under the variable name 'facilities'
    return render_template("search.html", facilities=mock_facilities)


# Route 2: The Upload Page
# We must explicitly tell Flask this route accepts 'POST' (submitting data) and 'GET' (viewing the page)
@app.route("/upload", methods=['GET', 'POST'])
def upload():
    # If the user clicked the Submit button, the method is POST
    if request.method == 'POST':
        
        # 1. Check if the file input field (named 'campd_file' in our HTML) is actually in the request
        if 'campd_file' not in request.files:
            flash("No file part found in the submission.", "danger") # "danger" makes the alert box red
            return redirect(request.url)
            
        file = request.files['campd_file']
        
        # 2. Check if the user clicked submit without actually selecting a file
        if file.filename == '':
            flash("No file selected. Please choose a .csv or .xlsx file.", "warning") # "warning" makes it yellow
            return redirect(request.url)
            
        # 3. If a file exists, this is where Ejlin's Pandas code will take over to read it.
        if file:
            # For now, we just pretend it was successful and send a green success message
            flash(f"Success! '{file.filename}' was uploaded and is ready for database ingestion.", "success")
            return redirect(url_for('index')) # Bounce them back to the home page after success
            
    # If the method is GET, just show them the blank upload form
    return render_template("upload.html")


# Route 3: The Detail Page
@app.route("/facility/<facility_id>")
def detail(facility_id):
    # Ejlin will use the 'facility_id' from the URL to query the specific units for this plant.
    # We pass a fake list of units so your Jinja loop works.
    mock_units = [
        {"id": "Unit 1", "type": "Tangential-fired boiler", "fuel": "Coal", "control": "Electrostatic Precipitator", "hours": "8,124"},
        {"id": "Unit 2", "type": "Tangential-fired boiler", "fuel": "Coal", "control": "Dry Scrubber", "hours": "7,890"}
    ]
    
    return render_template("detail.html", facility_id=facility_id, units=mock_units)


if __name__ == "__main__":
    app.run(debug=True)