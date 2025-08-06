# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Tilda-to-WordPress (t2w) migration tool that helps users convert websites exported from Tilda (a website builder) into WordPress sites. The tool provides a Flask-based web interface for managing projects, parsing Tilda HTML exports, and migrating content to WordPress using the REST API.

## Development Commands

### Running the Application
```bash
# Start the Flask development server
python app.py

# The app will run on http://localhost:5000 by default
```

### Dependencies
```bash
# Install required packages
pip install -r requirements.txt
```

### Testing
No test suite is currently configured. Manual testing is done through the web interface.

## Architecture

### Core Components

1. **app.py** - Main Flask application (1188 lines)
   - Handles web routes, file uploads, project management
   - Orchestrates parsing and migration workflows
   - Provides real-time migration progress via Server-Sent Events

2. **parser.py** - Tilda HTML parser (598 lines)
   - Extracts content from Tilda HTML exports
   - Handles menu parsing with support for multiple Tilda navigation patterns (T228, T456, etc.)
   - Preserves content hierarchy and document order

3. **migration.py** - WordPress migration manager
   - Handles WordPress REST API authentication
   - Creates pages with proper hierarchy
   - Automatically creates navigation menus using WordPress 6.8+ native API

4. **wordpress_api.py** - WordPress API wrapper
   - Abstracts WordPress REST API interactions
   - Handles authentication, media uploads, page creation

5. **wordpress_menu_manager.py** - Menu creation logic
   - Creates WordPress menus from parsed Tilda navigation
   - Maintains menu hierarchy and links to migrated pages

6. **progress_tracker.py** - Migration progress tracking
   - Logs migration operations
   - Provides real-time status updates

### Data Flow

1. User uploads Tilda .zip export → stored in `projects/{project_name}/upload/`
2. Zip extraction → content extracted to `projects/{project_name}/extracted/`
3. Parser analyzes HTML → structured data saved to `projects/{project_name}/parsed_output/`
   - `menu.json` - navigation structure
   - `pages/*.json` - individual page content
4. Migration to WordPress → logs saved to `projects/{project_name}/migration_logs/`

### Key Features

- **Multi-project support**: Manage multiple Tilda-to-WordPress migrations
- **Content quality analysis**: Analyzes parsed content and provides improvement suggestions
- **Real-time progress**: Server-Sent Events for live migration updates
- **Error handling**: Comprehensive error messages with recovery suggestions
- **Menu preservation**: Maintains navigation hierarchy from Tilda

### WordPress Requirements

- WordPress 5.9+ (6.8+ recommended for full menu API support)
- Administrator user with Application Password
- REST API must be accessible

### Important Patterns

- All file paths must be absolute (security measure)
- Parsed data is stored as structured JSON for flexibility
- Migration is asynchronous using background threads
- Menu creation uses native WordPress REST API (no plugins required)