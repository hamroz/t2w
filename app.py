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

def get_workflow_status(project_path):
    """Get the current workflow completion status for a project."""
    status = {
        'project_created': True,  # If we're calling this, project exists
        'files_uploaded': False,
        'files_extracted': False,
        'content_parsed': False,
        'wordpress_tested': False,
        'migration_completed': False
    }
    
    # Check if files are uploaded
    upload_folder = os.path.join(project_path, 'upload')
    if os.path.exists(upload_folder) and os.listdir(upload_folder):
        status['files_uploaded'] = True
    
    # Check if files are extracted
    extracted_folder = os.path.join(project_path, 'extracted')
    if os.path.exists(extracted_folder) and os.listdir(extracted_folder):
        status['files_extracted'] = True
    
    # Check if content is parsed
    parsed_data = load_parsed_data(project_path)
    if parsed_data and parsed_data.get('pages'):
        status['content_parsed'] = True
    
    # Check if WordPress connection was tested
    migration_history = MigrationManager.get_project_migration_history(project_path)
    if migration_history:
        status['wordpress_tested'] = True
        # Check if any migration was completed successfully
        for migration in migration_history:
            if migration.get('status') == 'completed':
                status['migration_completed'] = True
                break
    
    return status

def get_project_statistics(project_path):
    """Get detailed statistics about the project."""
    stats = {
        'uploaded_files_count': 0,
        'extracted_files_count': 0,
        'parsed_pages_count': 0,
        'total_content_blocks': 0,
        'menu_items_count': 0,
        'migration_attempts': 0,
        'successful_migrations': 0,
        'last_activity': None
    }
    
    # Count uploaded files
    upload_folder = os.path.join(project_path, 'upload')
    if os.path.exists(upload_folder):
        stats['uploaded_files_count'] = len([f for f in os.listdir(upload_folder) if os.path.isfile(os.path.join(upload_folder, f))])
    
    # Count extracted files
    extracted_folder = os.path.join(project_path, 'extracted')
    if os.path.exists(extracted_folder):
        for root, dirs, files in os.walk(extracted_folder):
            stats['extracted_files_count'] += len(files)
    
    # Analyze parsed data
    parsed_data = load_parsed_data(project_path)
    if parsed_data:
        stats['parsed_pages_count'] = len(parsed_data.get('pages', []))
        stats['menu_items_count'] = len(parsed_data.get('menu', []))
        
        # Count total content blocks
        for page in parsed_data.get('pages', []):
            stats['total_content_blocks'] += len(page.get('content', []))
    
    # Analyze migration history
    migration_history = MigrationManager.get_project_migration_history(project_path)
    if migration_history:
        stats['migration_attempts'] = len(migration_history)
        stats['successful_migrations'] = len([m for m in migration_history if m.get('status') == 'completed'])
        
        # Get last activity from most recent migration
        if migration_history:
            latest_migration = migration_history[0]
            stats['last_activity'] = latest_migration.get('started_at', '')
    
    return stats

def analyze_content_quality(parsed_data):
    """Analyze the quality and completeness of parsed content."""
    if not parsed_data or not parsed_data.get('pages'):
        return {
            'overall_score': 0,
            'completeness_score': 0,
            'issues': ['No parsed content available'],
            'suggestions': ['Run the parser to analyze content quality'],
            'statistics': {}
        }
    
    pages = parsed_data.get('pages', [])
    menu = parsed_data.get('menu', [])
    
    # Calculate statistics
    total_pages = len(pages)
    total_content_blocks = sum(len(page.get('content', [])) for page in pages)
    pages_with_content = len([page for page in pages if page.get('content')])
    pages_with_titles = len([page for page in pages if page.get('title') and page['title'].strip()])
    
    # Content type distribution
    content_types = {'heading': 0, 'paragraph': 0, 'button': 0, 'image': 0, 'other': 0}
    for page in pages:
        for block in page.get('content', []):
            block_type = block.get('type', 'other')
            if block_type in content_types:
                content_types[block_type] += 1
            else:
                content_types['other'] += 1
    
    # Identify issues
    issues = []
    suggestions = []
    
    if total_pages == 0:
        issues.append('No pages found in parsed data')
        suggestions.append('Check if the Tilda export contains valid HTML files')
    
    if pages_with_content < total_pages:
        missing_content_pages = total_pages - pages_with_content
        issues.append(f'{missing_content_pages} pages have no content blocks')
        suggestions.append('Review pages with missing content - they may need manual attention')
    
    if pages_with_titles < total_pages:
        missing_title_pages = total_pages - pages_with_titles
        issues.append(f'{missing_title_pages} pages have missing or empty titles')
        suggestions.append('Ensure all pages have descriptive titles for better SEO')
    
    if not menu:
        issues.append('No menu structure found')
        suggestions.append('Check if the main page contains navigation elements')
    
    if content_types['heading'] == 0 and total_content_blocks > 0:
        issues.append('No headings found in content')
        suggestions.append('Content should include headings for better structure and SEO')
    
    if content_types['paragraph'] == 0 and total_content_blocks > 0:
        issues.append('No paragraphs found in content')
        suggestions.append('Check if text content is being parsed correctly')
    
    # Calculate quality scores
    completeness_score = 0
    if total_pages > 0:
        completeness_score = (
            (pages_with_content / total_pages) * 40 +
            (pages_with_titles / total_pages) * 30 +
            (min(len(menu), 10) / 10) * 20 +
            (min(total_content_blocks, 50) / 50) * 10
        )
    
    # Overall score considers completeness and content diversity
    diversity_score = 0
    if total_content_blocks > 0:
        non_zero_types = len([count for count in content_types.values() if count > 0])
        diversity_score = (non_zero_types / len(content_types)) * 100
    
    overall_score = (completeness_score * 0.7 + diversity_score * 0.3)
    
    # Add positive feedback
    if overall_score > 80:
        suggestions.append('✅ Excellent content quality! Ready for migration.')
    elif overall_score > 60:
        suggestions.append('✅ Good content quality with minor improvements needed.')
    elif overall_score > 40:
        suggestions.append('⚠️ Content quality needs improvement before migration.')
    else:
        suggestions.append('❌ Significant content issues detected. Review parsing results.')
    
    return {
        'overall_score': round(overall_score, 1),
        'completeness_score': round(completeness_score, 1),
        'diversity_score': round(diversity_score, 1),
        'issues': issues,
        'suggestions': suggestions,
        'statistics': {
            'total_pages': total_pages,
            'pages_with_content': pages_with_content,
            'pages_with_titles': pages_with_titles,
            'total_content_blocks': total_content_blocks,
            'menu_items': len(menu),
            'content_types': content_types
        }
    }

def get_page_content_quality(page):
    """Analyze quality of a specific page's content."""
    content = page.get('content', [])
    title = page.get('title', '').strip()
    slug = page.get('slug', '').strip()
    
    issues = []
    suggestions = []
    
    # Check title quality
    if not title:
        issues.append('Missing page title')
        suggestions.append('Add a descriptive title for SEO and navigation')
    elif len(title) > 60:
        issues.append('Title is too long (>60 characters)')
        suggestions.append('Shorten title for better SEO')
    elif len(title) < 10:
        issues.append('Title is very short (<10 characters)')
        suggestions.append('Consider a more descriptive title')
    
    # Check content structure
    if not content:
        issues.append('No content blocks found')
        suggestions.append('Check if page content was parsed correctly')
    else:
        headings = [block for block in content if block.get('type') == 'heading']
        paragraphs = [block for block in content if block.get('type') == 'paragraph']
        
        if not headings:
            issues.append('No headings found')
            suggestions.append('Add headings to improve content structure')
        
        if not paragraphs:
            issues.append('No paragraph content found')
            suggestions.append('Check if text content is being parsed correctly')
        
        # Check content length
        total_text_length = sum(len(block.get('text', '')) for block in content if block.get('text'))
        if total_text_length < 100:
            issues.append('Very little text content')
            suggestions.append('Ensure all page content is being captured')
        elif total_text_length > 5000:
            issues.append('Very long content')
            suggestions.append('Consider breaking into multiple pages')
    
    # Check slug quality
    if not slug or slug == '/':
        if title.lower() != 'home' and title.lower() != 'index':
            issues.append('Missing or empty slug')
            suggestions.append('Generate SEO-friendly slug from title')
    
    quality_score = 100
    quality_score -= len(issues) * 15  # Deduct points for each issue
    quality_score = max(0, quality_score)  # Don't go below 0
    
    return {
        'quality_score': quality_score,
        'issues': issues,
        'suggestions': suggestions,
        'content_stats': {
            'total_blocks': len(content),
            'headings_count': len([b for b in content if b.get('type') == 'heading']),
            'paragraphs_count': len([b for b in content if b.get('type') == 'paragraph']),
            'buttons_count': len([b for b in content if b.get('type') == 'button']),
            'text_length': sum(len(block.get('text', '')) for block in content if block.get('text'))
        }
    }

def handle_upload_error(error_type, filename=None, details=None):
    """Generate user-friendly error messages for upload issues."""
    error_messages = {
        'no_file': {
            'message': 'No file was selected for upload.',
            'suggestions': ['Please select a .zip file exported from Tilda before uploading.'],
            'recovery': 'Select a file and try again.'
        },
        'invalid_extension': {
            'message': f'Invalid file type uploaded: {filename or "unknown file"}',
            'suggestions': [
                'Only .zip files are supported.',
                'Ensure you exported your Tilda project as a .zip archive.',
                'Check that the file extension is .zip (not .rar, .7z, etc.)'
            ],
            'recovery': 'Upload a valid .zip file instead.'
        },
        'corrupted_zip': {
            'message': f'The uploaded file "{filename or "unknown"}" is not a valid ZIP archive.',
            'suggestions': [
                'The file may be corrupted during download or transfer.',
                'Re-export your project from Tilda and download a fresh copy.',
                'Ensure the download completed successfully.'
            ],
            'recovery': 'Try re-uploading a fresh export from Tilda.'
        },
        'no_html_files': {
            'message': 'No HTML files found in the uploaded ZIP archive.',
            'suggestions': [
                'Ensure you exported the complete project from Tilda, not just assets.',
                'Check that the export includes index.html and other page files.',
                'Verify this is a Tilda project export, not a different type of archive.'
            ],
            'recovery': 'Export the complete project from Tilda and upload again.'
        },
        'extraction_failed': {
            'message': f'Failed to extract the uploaded file: {details or "unknown error"}',
            'suggestions': [
                'The ZIP file may be password protected.',
                'Check if the file is corrupted.',
                'Ensure the file size is reasonable (not too large).'
            ],
            'recovery': 'Try uploading a different export or contact support.'
        }
    }
    
    return error_messages.get(error_type, {
        'message': f'An unexpected error occurred: {details or "unknown error"}',
        'suggestions': ['Please try again or contact support if the issue persists.'],
        'recovery': 'Refresh the page and try again.'
    })

def handle_parser_error(error_type, details=None):
    """Generate user-friendly error messages for parser issues."""
    error_messages = {
        'no_extracted_files': {
            'message': 'No extracted files found to parse.',
            'suggestions': [
                'Upload and extract a Tilda project first.',
                'Check that the extraction completed successfully.'
            ],
            'recovery': 'Upload a .zip file and ensure it extracts properly.'
        },
        'no_html_files': {
            'message': 'No HTML files found in the extracted content.',
            'suggestions': [
                'Ensure the uploaded file is a complete Tilda export.',
                'Check that index.html and page files are present.',
                'Verify the extraction was successful.'
            ],
            'recovery': 'Upload a complete Tilda project export.'
        },
        'parsing_failed': {
            'message': f'Content parsing failed: {details or "unknown error"}',
            'suggestions': [
                'The HTML structure may be unusual or corrupted.',
                'Try re-exporting the project from Tilda.',
                'Check for any custom code that might interfere with parsing.'
            ],
            'recovery': 'Try with a fresh export or contact support.'
        },
        'no_content_found': {
            'message': 'No content was extracted from the HTML files.',
            'suggestions': [
                'The pages may use unsupported Tilda blocks.',
                'Check if the pages contain actual content (not just navigation).',
                'Verify this is a standard Tilda project export.'
            ],
            'recovery': 'Review the HTML files and try parsing with different settings.'
        }
    }
    
    return error_messages.get(error_type, {
        'message': f'Parser error: {details or "unknown error"}',
        'suggestions': ['Try re-running the parser or contact support.'],
        'recovery': 'Check the extracted files and try again.'
    })

def handle_migration_error(error_type, details=None):
    """Generate user-friendly error messages for migration issues."""
    error_messages = {
        'no_parsed_data': {
            'message': 'No parsed content available for migration.',
            'suggestions': [
                'Run the content parser first to analyze your Tilda export.',
                'Ensure the parsing completed successfully.',
                'Check that pages were found during parsing.'
            ],
            'recovery': 'Go to the Extraction & Parsing tab and run the parser.'
        },
        'wordpress_connection_failed': {
            'message': f'WordPress connection failed: {details or "connection error"}',
            'suggestions': [
                'Check your WordPress site URL is correct and accessible.',
                'Verify your username and application password are correct.',
                'Ensure your WordPress user has administrator privileges.',
                'Check if your hosting provider blocks REST API access.'
            ],
            'recovery': 'Test the connection again with correct credentials.'
        },
        'wordpress_auth_failed': {
            'message': 'WordPress authentication failed.',
            'suggestions': [
                'Generate a new Application Password in WordPress Admin → Users → Your Profile.',
                'Ensure you are using an Application Password, not your regular password.',
                'Check that your username is correct (not email address).',
                'Verify your user account has administrator role.'
            ],
            'recovery': 'Update your credentials and test the connection again.'
        },
        'migration_failed': {
            'message': f'Migration process failed: {details or "unknown error"}',
            'suggestions': [
                'Check your WordPress site is accessible and functioning.',
                'Ensure sufficient storage space on your hosting account.',
                'Verify your hosting provider allows REST API requests.',
                'Check for plugin conflicts that might block the migration.'
            ],
            'recovery': 'Review the migration logs and try again.'
        }
    }
    
    return error_messages.get(error_type, {
        'message': f'Migration error: {details or "unknown error"}',
        'suggestions': ['Check the logs for more details.'],
        'recovery': 'Contact support if the issue persists.'
    })

def flash_enhanced_error(error_info, category='error'):
    """Flash an enhanced error message with suggestions."""
    message = error_info['message']
    if error_info.get('suggestions'):
        message += f" Suggestions: {'; '.join(error_info['suggestions'])}"
    if error_info.get('recovery'):
        message += f" To resolve: {error_info['recovery']}"
    
    flash(message, category)

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
    
    # Get workflow status and statistics for enhanced dashboard
    workflow_status = get_workflow_status(project_path)
    project_stats = get_project_statistics(project_path)
    recommendations = generate_workflow_recommendations(workflow_status, project_stats)
    
    # Add content quality analysis
    content_quality = analyze_content_quality(parsed_data) if parsed_data else None

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
                           parsed_data=parsed_data,
                           workflow_status=workflow_status,
                           project_stats=project_stats,
                           recommendations=recommendations,
                           content_quality=content_quality)

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
    try:
        structured_data = parse_tilda_export(project_path, include_images)
        
        if "error" in structured_data:
            # Determine error type based on error message
            error_msg = structured_data['error']
            if "not found" in error_msg.lower():
                error_info = handle_parser_error('no_extracted_files')
            elif "no html" in error_msg.lower():
                error_info = handle_parser_error('no_html_files')
            else:
                error_info = handle_parser_error('parsing_failed', details=error_msg)
            flash_enhanced_error(error_info)
        else:
            # Check if any content was actually found
            pages_found = len(structured_data.get('pages', []))
            if pages_found == 0:
                error_info = handle_parser_error('no_content_found')
                flash_enhanced_error(error_info, 'warning')
            else:
                # Save the structured data to the new directory structure
                save_parsed_data(project_path, structured_data)
                images_msg = " (excluding images)" if not include_images else " (including images)"
                flash(f"✅ Parsing complete! Found {pages_found} pages{images_msg}.", 'success')
                
                # Add helpful info about what was found
                total_blocks = sum(len(page.get('content', [])) for page in structured_data.get('pages', []))
                menu_items = len(structured_data.get('menu', []))
                if total_blocks > 0:
                    flash(f"📊 Extracted {total_blocks} content blocks and {menu_items} menu items.", 'info')
    
    except Exception as e:
        error_info = handle_parser_error('parsing_failed', details=str(e))
        flash_enhanced_error(error_info)

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

@app.route('/project/<project_name>/page/<path:page_slug>')
def view_parsed_page(project_name, page_slug):
    """Display the parsed content of a specific page with copy functionality."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        flash(f"Project '{project_name}' not found.", 'error')
        return redirect(url_for('index'))

    # Load all parsed data to find the specific page
    parsed_data = load_parsed_data(project_path)
    if not parsed_data or not parsed_data.get('pages'):
        flash('No parsed data found. Please run the parser first.', 'error')
        return redirect(url_for('project_view', project_name=project_name))

    # Find the page with the matching slug
    target_page = None
    for page in parsed_data['pages']:
        if page.get('slug') == f"/{page_slug}" or page.get('slug') == page_slug:
            target_page = page
            break
    
    if not target_page:
        flash(f"Page with slug '{page_slug}' not found.", 'error')
        return redirect(url_for('project_view', project_name=project_name))

    # Add content quality analysis for this specific page
    page_quality = get_page_content_quality(target_page)

    return render_template('page_view.html', 
                         project_name=project_name,
                         page=target_page,
                         all_pages=parsed_data['pages'],
                         page_quality=page_quality)

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
        error_info = handle_upload_error('no_file')
        flash_enhanced_error(error_info)
        return redirect(url_for('project_view', project_name=project_name))

    file = request.files['file']

    if file.filename == '':
        error_info = handle_upload_error('no_file')
        flash_enhanced_error(error_info)
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
            error_info = handle_upload_error('corrupted_zip', filename=filename)
            flash_enhanced_error(error_info)
            return redirect(url_for('project_view', project_name=project_name))
        except Exception as e:
            error_info = handle_upload_error('extraction_failed', filename=filename, details=str(e))
            flash_enhanced_error(error_info)
            return redirect(url_for('project_view', project_name=project_name))

        if not any(fname.lower().endswith('.html') for fname in extracted_files):
            error_info = handle_upload_error('no_html_files')
            flash_enhanced_error(error_info, 'warning')
        else:
            flash(f"✅ '{filename}' has been successfully uploaded and extracted.", 'success')

        return redirect(url_for('project_view', project_name=project_name))

    else:
        error_info = handle_upload_error('invalid_extension', filename=file.filename)
        flash_enhanced_error(error_info)
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
    page_template = request.form.get('page_template', '')
    
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
                
                # Prepare migration config
                migration_config = {'page_template': page_template}
                
                result = migration_manager.start_migration(migration_config)
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

@app.route('/project/<project_name>/workflow-status')
def get_project_workflow_status(project_name):
    """API endpoint to get workflow status for a project."""
    project_path = get_secure_project_path(project_name)
    if not project_path:
        return jsonify({'error': 'Project not found'}), 404
    
    workflow_status = get_workflow_status(project_path)
    project_stats = get_project_statistics(project_path)
    
    return jsonify({
        'workflow': workflow_status,
        'statistics': project_stats,
        'recommendations': generate_workflow_recommendations(workflow_status, project_stats)
    })

def generate_workflow_recommendations(workflow_status, stats):
    """Generate smart recommendations based on current project state."""
    recommendations = []
    
    if not workflow_status['files_uploaded']:
        recommendations.append({
            'type': 'action',
            'priority': 'high',
            'title': 'Upload Tilda Export',
            'description': 'Upload your .zip file exported from Tilda to begin the migration process.',
            'action': 'upload'
        })
    elif not workflow_status['files_extracted']:
        recommendations.append({
            'type': 'info',
            'priority': 'medium',
            'title': 'Files Uploaded Successfully',
            'description': f'{stats["uploaded_files_count"]} file(s) uploaded and ready for extraction.',
            'action': None
        })
    elif not workflow_status['content_parsed']:
        recommendations.append({
            'type': 'action',
            'priority': 'high',
            'title': 'Run Content Parser',
            'description': 'Parse the extracted files to analyze content structure and prepare for migration.',
            'action': 'parse'
        })
    elif not workflow_status['wordpress_tested']:
        recommendations.append({
            'type': 'action',
            'priority': 'high',
            'title': 'Configure WordPress',
            'description': f'{stats["parsed_pages_count"]} pages ready for migration. Set up your WordPress connection.',
            'action': 'wordpress'
        })
    elif not workflow_status['migration_completed']:
        recommendations.append({
            'type': 'action',
            'priority': 'high',
            'title': 'Start Migration',
            'description': f'Everything is ready! Migrate {stats["parsed_pages_count"]} pages to WordPress.',
            'action': 'migrate'
        })
    else:
        recommendations.append({
            'type': 'success',
            'priority': 'low',
            'title': 'Migration Complete',
            'description': f'Successfully completed {stats["successful_migrations"]} migration(s). Review results or start a new project.',
            'action': 'review'
        })
    
    # Add additional contextual recommendations
    if stats['total_content_blocks'] > 100:
        recommendations.append({
            'type': 'info',
            'priority': 'medium',
            'title': 'Large Content Volume',
            'description': f'{stats["total_content_blocks"]} content blocks detected. Consider reviewing content before migration.',
            'action': 'review_content'
        })
    
    if stats['migration_attempts'] > 1 and stats['successful_migrations'] == 0:
        recommendations.append({
            'type': 'warning',
            'priority': 'high',
            'title': 'Migration Issues Detected',
            'description': f'{stats["migration_attempts"]} attempts with no successful migrations. Check logs for issues.',
            'action': 'troubleshoot'
        })
    
    return recommendations

if __name__ == "__main__":
    app.run(debug=True) 