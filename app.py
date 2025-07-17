import os
import zipfile
import datetime
import shutil
import mimetypes
import json
from flask import Flask, request, render_template, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
from parser import parse_tilda_export, save_parsed_data

# Define allowed file extensions
ALLOWED_EXTENSIONS = {'zip'}

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Define path for projects
app.config['PROJECTS_FOLDER'] = 'projects'
os.makedirs(app.config['PROJECTS_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_projects():
    """Scan the projects directory and return a list of project names."""
    projects = []
    for item in os.listdir(app.config['PROJECTS_FOLDER']):
        if os.path.isdir(os.path.join(app.config['PROJECTS_FOLDER'], item)):
            projects.append(item)
    return sorted(projects)

def get_secure_project_path(project_name):
    """Get and validate the absolute path for a project."""
    project_path = os.path.join(app.config['PROJECTS_FOLDER'], project_name)
    # Prevent traversal attacks
    if not os.path.normpath(project_path).startswith(os.path.normpath(app.config['PROJECTS_FOLDER'])):
        return None
    if not os.path.isdir(project_path):
        return None
    return project_path

def get_secure_subpath(project_path, subpath):
    """Get and validate a subpath within a project's extracted folder."""
    extracted_root = os.path.join(project_path, 'extracted')
    full_path = os.path.join(extracted_root, subpath)
    # Normalize paths to prevent traversal attacks (e.g., ../../)
    secure_path = os.path.normpath(os.path.abspath(full_path))
    secure_root = os.path.normpath(os.path.abspath(extracted_root))
    if not secure_path.startswith(secure_root):
        return None
    return secure_path

@app.route('/', methods=['GET'])
def index():
    """Render the main page with a list of projects."""
    projects = get_projects()
    return render_template('index.html', projects=projects)

@app.route('/create_project', methods=['POST'])
def create_project():
    """Create a new project directory."""
    project_name = request.form.get('project_name')
    if not project_name or not project_name.strip():
        flash('Project name cannot be empty.', 'error')
        return redirect(url_for('index'))
    
    sanitized_name = secure_filename(project_name.strip())
    if not sanitized_name:
        flash('Invalid project name. Please use letters, numbers, dashes, or underscores.', 'error')
        return redirect(url_for('index'))

    project_path = os.path.join(app.config['PROJECTS_FOLDER'], sanitized_name)
    
    if os.path.exists(project_path):
        flash(f"Project '{sanitized_name}' already exists.", 'error')
    else:
        os.makedirs(os.path.join(project_path, 'upload'))
        os.makedirs(os.path.join(project_path, 'extracted'))
        flash(f"Project '{sanitized_name}' created successfully.", 'success')
        
    return redirect(url_for('index'))

@app.route('/project/<project_name>')
@app.route('/project/<project_name>/browse/')
@app.route('/project/<project_name>/browse/<path:subpath>')
def project_view(project_name, subpath=''):
    """Display the dashboard and file browser for a specific project."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    # Load parsed data if it exists
    parsed_data = None
    parsed_data_path = os.path.join(project_path, 'parsed_data.json')
    if os.path.exists(parsed_data_path):
        with open(parsed_data_path, 'r', encoding='utf-8') as f:
            parsed_data = json.load(f)

    browse_path = get_secure_subpath(project_path, subpath)
    if not browse_path or not os.path.exists(browse_path):
        flash('Invalid file path.', 'error')
        return redirect(url_for('project_view', project_name=project_name))

    # Scan the directory for files and folders
    items = os.listdir(browse_path)
    dirs = sorted([d for d in items if os.path.isdir(os.path.join(browse_path, d))])
    files = sorted([f for f in items if os.path.isfile(os.path.join(browse_path, f))])

    # Create breadcrumbs for navigation
    breadcrumbs = []
    if subpath:
        parts = subpath.split(os.sep)
        for i, part in enumerate(parts):
            path_so_far = os.path.join(*parts[:i+1])
            breadcrumbs.append({'name': part, 'path': path_so_far})
            
    upload_folder = os.path.join(project_path, 'upload')
    uploaded_files = [f for f in os.listdir(upload_folder) if os.path.isfile(os.path.join(upload_folder, f))]
    
    return render_template('project.html', 
                           project_name=project_name, 
                           uploaded_files=uploaded_files,
                           current_path=subpath,
                           directories=dirs,
                           files=files,
                           breadcrumbs=breadcrumbs,
                           parsed_data=parsed_data)

@app.route('/project/<project_name>/parse')
def run_parser(project_name):
    """Run the Tilda parser on the project's extracted files."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    flash("Starting the parsing process...", "info")
    
    # Run the parser
    structured_data = parse_tilda_export(project_path)
    
    if "error" in structured_data:
        flash(f"Parser error: {structured_data['error']}", 'error')
    else:
        # Save the structured data to a file
        save_parsed_data(project_path, structured_data)
        flash("Parsing complete. Found {} pages.".format(len(structured_data.get('pages', []))), 'success')

    return redirect(url_for('project_view', project_name=project_name))

@app.route('/project/<project_name>/download_json')
def download_json(project_name):
    """Allow downloading the parsed data as a JSON file."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))
        
    json_path = os.path.join(project_path, 'parsed_data.json')
    if not os.path.exists(json_path):
        flash("No parsed data found to download.", 'error')
        return redirect(url_for('project_view', project_name=project_name))

    return send_from_directory(directory=project_path, path='parsed_data.json', as_attachment=True)


@app.route('/project/<project_name>/view/<path:filepath>')
def view_file(project_name, filepath):
    """Display the content of a specific file."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    file_to_view = get_secure_subpath(project_path, filepath)
    if not file_to_view or not os.path.isfile(file_to_view):
        flash('File not found or is not a regular file.', 'error')
        return redirect(url_for('project_view', project_name=project_name))

    try:
        content = ""
        mimetype, _ = mimetypes.guess_type(file_to_view)
        is_text = mimetype and mimetype.startswith('text/')
        
        if is_text:
            with open(file_to_view, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        else:
            content = f"Cannot display file: content is not plain text (MIME type: {mimetype or 'unknown'})."

        return render_template('view_file.html', project_name=project_name, filepath=filepath, content=content, is_text=is_text)

    except Exception as e:
        flash(f"Could not read file: {e}", 'error')
        return redirect(url_for('project_view', project_name=project_name, subpath=os.path.dirname(filepath)))

@app.route('/project/<project_name>/delete', methods=['POST'])
def delete_project(project_name):
    """Delete a project."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))
    
    try:
        shutil.rmtree(project_path)
        flash(f"Project '{project_name}' has been deleted.", 'success')
    except OSError as e:
        flash(f"Error deleting project '{project_name}': {e}", 'error')

    return redirect(url_for('index'))

@app.route('/project/<project_name>/rename', methods=['GET', 'POST'])
def rename_project(project_name):
    """Rename a project."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        new_name = request.form.get('new_project_name')
        if not new_name or not new_name.strip():
            flash('New project name cannot be empty.', 'error')
            return redirect(url_for('rename_project', project_name=project_name))

        sanitized_new_name = secure_filename(new_name.strip())
        if not sanitized_new_name:
            flash('Invalid project name. Please use letters, numbers, dashes, or underscores.', 'error')
            return redirect(url_for('rename_project', project_name=project_name))
        
        if sanitized_new_name == project_name:
            flash('New name is the same as the old name.', 'warning')
            return redirect(url_for('project_view', project_name=sanitized_new_name))

        new_project_path = os.path.join(app.config['PROJECTS_FOLDER'], sanitized_new_name)
        if os.path.exists(new_project_path):
            flash(f"A project with the name '{sanitized_new_name}' already exists.", 'error')
            return redirect(url_for('rename_project', project_name=project_name))
        
        try:
            os.rename(project_path, new_project_path)
            flash(f"Project '{project_name}' has been renamed to '{sanitized_new_name}'.", 'success')
            return redirect(url_for('project_view', project_name=sanitized_new_name))
        except OSError as e:
            flash(f"Error renaming project: {e}", 'error')
            return redirect(url_for('index'))

    return render_template('rename_project.html', project_name=project_name)

@app.route('/project/<project_name>/upload', methods=['POST'])
def upload_file(project_name):
    """Handle file upload and extraction for a specific project."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('project_view', project_name=project_name))

    file = request.files['file']

    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('project_view', project_name=project_name))

    if file and allowed_file(file.filename):
        upload_path = os.path.join(project_path, 'upload')
        extracted_path = os.path.join(project_path, 'extracted')
        
        filename = secure_filename(file.filename)
        # To avoid clutter, let's just save one zip at a time.
        # Clear previous uploads before saving new one
        if os.path.exists(upload_path):
            shutil.rmtree(upload_path)
        os.makedirs(upload_path)
        saved_filepath = os.path.join(upload_path, filename)
        file.save(saved_filepath)

        # Clear previous extraction
        if os.path.exists(extracted_path):
            shutil.rmtree(extracted_path)
        os.makedirs(extracted_path)
        
        extracted_files = []
        try:
            with zipfile.ZipFile(saved_filepath, 'r') as zip_ref:
                zip_ref.extractall(extracted_path)
                extracted_files = zip_ref.namelist()
        except zipfile.BadZipFile:
            flash('Error: Uploaded file is not a valid ZIP archive.', 'error')
            return redirect(url_for('project_view', project_name=project_name))

        if not any(fname.lower().endswith('.html') for fname in extracted_files):
             flash('Warning: No HTML files found in the ZIP archive.', 'warning')
        else:
            flash(f"'{filename}' has been successfully uploaded and extracted.", 'success')

        return redirect(url_for('project_view', project_name=project_name))

    else:
        flash('Invalid file type. Please upload a .zip file.', 'error')
        return redirect(url_for('project_view', project_name=project_name))

if __name__ == "__main__":
    app.run(debug=True) 