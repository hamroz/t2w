import os
import zipfile
import datetime
import shutil
import mimetypes
import json
import threading
from flask import Flask, request, render_template, redirect, url_for, flash, send_from_directory, jsonify, Response
from werkzeug.utils import secure_filename
from parser import parse_tilda_export
from migration import MigrationManager
from progress_tracker import ProgressTracker
import time

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

def save_parsed_data(project_path, data):
    """Saves the structured data into a directory with separate JSON files."""
    output_dir = os.path.join(project_path, 'parsed_output')
    pages_dir = os.path.join(output_dir, 'pages')

    # Clean up old parsed data before saving new
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    
    os.makedirs(pages_dir, exist_ok=True)

    # Save the menu
    menu_data = data.get('menu', [])
    with open(os.path.join(output_dir, 'menu.json'), 'w', encoding='utf-8') as f:
        json.dump(menu_data, f, indent=4)

    # Save each page as a separate JSON file
    for page in data.get('pages', []):
        slug = page.get('slug', 'untitled').strip('/')
        if not slug:
            slug = 'home'
        filename = f"{secure_filename(slug)}.json"
        with open(os.path.join(pages_dir, filename), 'w', encoding='utf-8') as f:
            json.dump(page, f, indent=4)

def load_parsed_data(project_path):
    """Loads all parsed data from the structured directory."""
    output_dir = os.path.join(project_path, 'parsed_output')
    if not os.path.isdir(output_dir):
        return None

    data = {'menu': [], 'pages': []}
    
    # Load menu
    menu_path = os.path.join(output_dir, 'menu.json')
    if os.path.exists(menu_path):
        with open(menu_path, 'r', encoding='utf-8') as f:
            data['menu'] = json.load(f)

    # Load pages
    pages_dir = os.path.join(output_dir, 'pages')
    if os.path.isdir(pages_dir):
        for filename in os.listdir(pages_dir):
            if filename.endswith('.json'):
                with open(os.path.join(pages_dir, filename), 'r', encoding='utf-8') as f:
                    data['pages'].append(json.load(f))
                    
    return data

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

    # Load parsed data from the new structure
    parsed_data = load_parsed_data(project_path)

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

    # Get the include_images parameter from query string (default: True)
    include_images = request.args.get('include_images', 'true').lower() == 'true'
    
    flash("Starting the parsing process...", "info")
    
    # Run the parser with the include_images option
    structured_data = parse_tilda_export(project_path, include_images)
    
    if "error" in structured_data:
        flash(f"Parser error: {structured_data['error']}", 'error')
    else:
        # Save the structured data to the new directory structure
        save_parsed_data(project_path, structured_data)
        images_msg = " (excluding images)" if not include_images else " (including images)"
        flash("Parsing complete. Found {} pages{}.".format(len(structured_data.get('pages', [])), images_msg), 'success')

    return redirect(url_for('project_view', project_name=project_name))

@app.route('/project/<project_name>/download_json')
def download_json(project_name):
    """Allow downloading the parsed data as a JSON file."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))
        
    output_dir = os.path.join(project_path, 'parsed_output')
    if not os.path.isdir(output_dir):
        flash("No parsed data found to download.", 'error')
        return redirect(url_for('project_view', project_name=project_name))

    # To download the data, we'll zip the entire parsed_output directory
    shutil.make_archive(os.path.join(project_path, 'parsed_data'), 'zip', output_dir)
    
    return send_from_directory(directory=project_path, path='parsed_data.zip', as_attachment=True)


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

# Global storage for active migrations (in production, use Redis or database)
active_migrations = {}

@app.route('/project/<project_name>/wordpress')
def wordpress_migration(project_name):
    """WordPress migration page."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))
    
    # Load parsed data to show preview
    parsed_data = load_parsed_data(project_path)
    
    # Get migration history
    migration_history = MigrationManager.get_project_migration_history(project_path)
    
    return render_template('wordpress_migration.html', 
                         project_name=project_name,
                         parsed_data=parsed_data,
                         migration_history=migration_history)

@app.route('/project/<project_name>/wordpress/test-connection', methods=['POST'])
def test_wordpress_connection(project_name):
    """Test WordPress connection."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return jsonify({'success': False, 'message': 'Project not found'})
    
    wp_site_url = request.form.get('wp_site_url', '').strip()
    wp_username = request.form.get('wp_username', '').strip()
    wp_password = request.form.get('wp_password', '').strip()
    
    if not all([wp_site_url, wp_username, wp_password]):
        return jsonify({'success': False, 'message': 'All fields are required'})
    
    try:
        migration_manager = MigrationManager(project_path, wp_site_url, wp_username, wp_password)
        result = migration_manager.validate_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Connection test failed: {str(e)}'})

@app.route('/project/<project_name>/wordpress/start-migration', methods=['POST'])
def start_wordpress_migration(project_name):
    """Start WordPress migration in background."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return jsonify({'success': False, 'message': 'Project not found'})
    
    wp_site_url = request.form.get('wp_site_url', '').strip()
    wp_username = request.form.get('wp_username', '').strip()
    wp_password = request.form.get('wp_password', '').strip()
    
    if not all([wp_site_url, wp_username, wp_password]):
        return jsonify({'success': False, 'message': 'All WordPress fields are required'})
    
    # Check if migration is already running
    if project_name in active_migrations:
        return jsonify({'success': False, 'message': 'Migration already in progress for this project'})
    
    try:
        # Create migration manager
        migration_manager = MigrationManager(project_path, wp_site_url, wp_username, wp_password)
        
        # Start migration in background thread
        def run_migration():
            try:
                active_migrations[project_name] = migration_manager
                result = migration_manager.start_migration()
                # Keep migration manager available for progress tracking
                if not result['success']:
                    # Remove from active migrations if failed to start
                    active_migrations.pop(project_name, None)
            except Exception as e:
                migration_manager.tracker.log_operation(f"Migration error: {str(e)}", "ERROR")
                migration_manager.tracker.complete_migration(False)
            finally:
                # Remove from active migrations when complete
                active_migrations.pop(project_name, None)
        
        thread = threading.Thread(target=run_migration)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': 'Migration started'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to start migration: {str(e)}'})

@app.route('/project/<project_name>/wordpress/migration-status')
def get_migration_status(project_name):
    """Get current migration status."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return jsonify({'error': 'Project not found'})
    
    # Check if migration is currently active
    if project_name in active_migrations:
        migration_manager = active_migrations[project_name]
        status = migration_manager.get_migration_status()
        recent_logs = migration_manager.get_migration_logs(20)
        return jsonify({
            'status': status,
            'logs': recent_logs,
            'is_active': True
        })
    
    # If no active migration, try to get the latest completed migration
    migration_history = MigrationManager.get_project_migration_history(project_path)
    if migration_history:
        latest = migration_history[0]
        return jsonify({
            'status': latest,
            'logs': ProgressTracker.get_migration_log(project_path, latest['migration_id']).split('\n')[-20:],
            'is_active': False
        })
    
    return jsonify({'status': None, 'logs': [], 'is_active': False})

@app.route('/project/<project_name>/wordpress/migration-logs/<migration_id>')
def get_migration_details(project_name, migration_id):
    """Get detailed logs for a specific migration."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return jsonify({'error': 'Project not found'})
    
    details = MigrationManager.get_migration_details(project_path, migration_id)
    if not details:
        return jsonify({'error': 'Migration not found'})
    
    return jsonify(details)

@app.route('/project/<project_name>/wordpress/migration-stream')
def migration_log_stream(project_name):
    """Server-sent events stream for real-time migration progress."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return Response("data: {\"error\": \"Project not found\"}\n\n", mimetype='text/plain')
    
    def generate():
        last_percentage = -1
        last_log_count = 0
        completion_sent = False
        
        while True:
            try:
                if project_name in active_migrations:
                    migration_manager = active_migrations[project_name]
                    status = migration_manager.get_migration_status()
                    logs = migration_manager.get_migration_logs(100)
                    
                    # Send updates only if there are changes
                    if (status['percentage'] != last_percentage or 
                        len(logs) != last_log_count or
                        status['status'] in ['completed', 'failed']):
                        
                        data = {
                            'percentage': status['percentage'],
                            'current_operation': status['current_operation'],
                            'status': status['status'],
                            'new_logs': logs[last_log_count:] if len(logs) > last_log_count else []
                        }
                        
                        yield f"data: {json.dumps(data)}\n\n"
                        
                        last_percentage = status['percentage']
                        last_log_count = len(logs)
                        
                        # Mark completion as sent and break after a small delay
                        if status['status'] in ['completed', 'failed'] and not completion_sent:
                            completion_sent = True
                            time.sleep(2)  # Give time for the frontend to process the completion
                            break
                            
                elif completion_sent:
                    # Migration was active but is now complete
                    break
                else:
                    # Check if there's a recently completed migration
                    migration_history = MigrationManager.get_project_migration_history(project_path)
                    if migration_history:
                        latest = migration_history[0]
                        if latest['status'] in ['completed', 'failed']:
                            # Send the final status
                            data = {
                                'percentage': 100 if latest['status'] == 'completed' else latest.get('percentage', 0),
                                'current_operation': latest['current_operation'],
                                'status': latest['status'],
                                'new_logs': []
                            }
                            yield f"data: {json.dumps(data)}\n\n"
                            time.sleep(1)
                            break
                    
                    # No active migration and no recent completion
                    yield f"data: {{\"status\": \"no_active_migration\"}}\n\n"
                    break
                
                time.sleep(1)  # Update every second
                
            except Exception as e:
                yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
                break
    
    return Response(generate(), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True) 