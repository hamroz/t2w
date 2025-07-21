import os
import json
import time
from collections import defaultdict
from urllib.parse import urlparse
from wordpress_api import WordPressAPI
from wordpress_menu_manager import WordPressMenuCreator
from progress_tracker import ProgressTracker

class MigrationManager:
    """Manages the migration process from Tilda to WordPress."""
    
    def __init__(self, project_path, wp_site_url, wp_username, wp_password):
        """Initialize the migration manager."""
        self.project_path = project_path
        self.wp_api = WordPressAPI(wp_site_url, wp_username, wp_password)
        self.tracker = None
        self.page_mapping = {}  # Maps Tilda slug to WordPress page ID for hierarchy
        
    def validate_connection(self):
        """Test WordPress connection before starting migration."""
        return self.wp_api.test_connection()
    
    def load_parsed_data(self):
        """Load the parsed Tilda data from the project."""
        output_dir = os.path.join(self.project_path, 'parsed_output')
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
    
    def analyze_page_hierarchy(self, pages):
        """Analyze and organize pages by hierarchy based on their slugs."""
        hierarchy = defaultdict(list)
        root_pages = []
        
        for page in pages:
            slug = page['slug']
            slug_parts = slug.strip('/').split('/')
            
            if len(slug_parts) == 1 or slug == '/':
                # Root level page
                root_pages.append(page)
            else:
                # Child page - find its parent
                parent_slug = '/' + '/'.join(slug_parts[:-1])
                hierarchy[parent_slug].append(page)
        
        return root_pages, hierarchy
    
    def start_migration(self, migration_config=None):
        """Start the complete migration process."""
        # Initialize progress tracker
        self.tracker = ProgressTracker(self.project_path)
        
        try:
            # Load parsed data
            self.tracker.log_operation("Loading parsed data...")
            data = self.load_parsed_data()
            if not data:
                raise Exception("No parsed data found. Please run the parser first.")
            
            pages = data.get('pages', [])
            menu = data.get('menu', [])
            
            if not pages:
                raise Exception("No pages found in parsed data.")
            
            # Test WordPress connection
            self.tracker.log_operation("Testing WordPress connection...")
            connection_result = self.validate_connection()
            if not connection_result['success']:
                raise Exception(f"WordPress connection failed: {connection_result['message']}")
            
            self.tracker.log_operation(f"✓ {connection_result['message']}")
            
            # Start migration
            self.tracker.start_migration(len(pages))
            
            # Analyze page hierarchy
            self.tracker.log_operation("Analyzing page hierarchy...")
            root_pages, hierarchy = self.analyze_page_hierarchy(pages)
            
            # Migrate pages (root pages first, then children)
            self.tracker.log_operation("Starting page migration...")
            self._migrate_pages_hierarchical(root_pages, hierarchy)
            
            # Create menu (optional - WordPress REST API has limited menu support)
            if menu:
                self.tracker.log_operation("Processing menu structure...")
                self._process_menu(menu)
            
            # Complete migration
            success = self.tracker.status['failed_pages'] == 0
            self.tracker.complete_migration(success)
            
            return {
                'success': True,
                'migration_id': self.tracker.migration_id,
                'status': self.tracker.get_status()
            }
            
        except Exception as e:
            if self.tracker:
                self.tracker.log_operation(f"Migration failed: {str(e)}", "ERROR")
                self.tracker.complete_migration(False)
            
            return {
                'success': False,
                'error': str(e),
                'migration_id': self.tracker.migration_id if self.tracker else None
            }
    
    def _migrate_pages_hierarchical(self, root_pages, hierarchy):
        """Migrate pages maintaining hierarchy."""
        # First, migrate all root pages
        for page in root_pages:
            self._migrate_single_page(page)
        
        # Then migrate child pages recursively
        for page in root_pages:
            self._migrate_children(page['slug'], hierarchy)
    
    def _migrate_children(self, parent_slug, hierarchy):
        """Recursively migrate child pages."""
        children = hierarchy.get(parent_slug, [])
        parent_wp_id = self.page_mapping.get(parent_slug)
        
        for child_page in children:
            self._migrate_single_page(child_page, parent_wp_id)
            # Recursively migrate grandchildren
            self._migrate_children(child_page['slug'], hierarchy)
    
    def _migrate_single_page(self, page, parent_id=None):
        """Migrate a single page to WordPress."""
        title = page['title']
        slug = page['slug'].strip('/')
        content_blocks = page.get('content', [])
        
        # Handle root page slug
        if not slug:
            slug = 'home'
        
        self.tracker.log_operation(f"Creating page: {title} ({page['slug']})")
        
        try:
            # Check if page already exists
            existing_page = self.wp_api.get_page_by_slug(slug)
            if existing_page:
                self.tracker.log_page_skipped(
                    title, 
                    page['slug'], 
                    f"Page with slug '{slug}' already exists (ID: {existing_page['id']})"
                )
                # Still map it for hierarchy purposes
                self.page_mapping[page['slug']] = existing_page['id']
                return
            
            # Create the page
            result = self.wp_api.create_page(
                title=title,
                slug=slug,
                content_blocks=content_blocks,
                parent_id=parent_id,
                status='publish'
            )
            
            if result['success']:
                # Store mapping for children
                self.page_mapping[page['slug']] = result['page_id']
                self.tracker.log_page_success(title, page['slug'], result['url'])
            else:
                self.tracker.log_page_failure(title, page['slug'], result['message'])
                
        except Exception as e:
            self.tracker.log_page_failure(title, page['slug'], str(e))
    
    def _process_menu(self, menu_items):
        """Create primary menu for fuseservice theme using native WordPress 6.8+ REST API."""
        try:
            self.tracker.log_operation("Creating primary menu using WordPress native REST API...")
            
            # Debug: Log menu structure
            self.tracker.log_operation(f"Menu data contains {len(menu_items)} top-level items")
            for i, item in enumerate(menu_items):
                title = item.get('title', 'No title')
                slug = item.get('slug', 'No slug')
                submenu_count = len(item.get('submenu', []))
                self.tracker.log_operation(f"  Item {i+1}: '{title}' -> {slug} ({submenu_count} subitems)")
            
            # Initialize menu creator
            menu_creator = WordPressMenuCreator(self.wp_api)
            
            # Create menu with proper page linking using native API
            menu_result = menu_creator.create_menu_with_native_api(
                menu_items, 
                self.page_mapping, 
                "Main Navigation"
            )
            
            if menu_result['success']:
                self.tracker.log_operation(
                    f"✓ Primary menu created successfully: {menu_result['message']}"
                )
                self.tracker.log_operation(
                    f"✓ Menu assigned to 'primary' location for fuseservice theme"
                )
            else:
                self.tracker.log_operation(
                    f"⚠ Menu creation issue: {menu_result['message']}", 
                    "WARNING"
                )
                # Check if it's a permission issue
                if "403" in str(menu_result.get('message', '')) or "manage_options" in str(menu_result.get('error', '')):
                    self.tracker.log_operation(
                        "📝 Note: Menu creation requires 'manage_options' capability. Your WordPress user may need administrator role.", 
                        "INFO"
                    )
                else:
                    self.tracker.log_operation(
                        "📝 Manual menu setup may be required in WordPress Admin → Appearance → Menus", 
                        "INFO"
                    )
                
        except Exception as e:
            self.tracker.log_operation(f"Menu creation error: {str(e)}", "WARNING")
            self.tracker.log_operation(
                "📝 Menu can be created manually in WordPress Admin → Appearance → Menus", 
                "INFO"
            )
    
    def get_migration_status(self):
        """Get current migration status."""
        if not self.tracker:
            return None
        return self.tracker.get_status()
    
    def get_migration_logs(self, limit=100):
        """Get recent migration logs."""
        if not self.tracker:
            return []
        return self.tracker.get_recent_logs(limit)
    
    @staticmethod
    def get_project_migration_history(project_path):
        """Get migration history for a project."""
        return ProgressTracker.get_migration_history(project_path)
    
    @staticmethod
    def get_migration_details(project_path, migration_id):
        """Get detailed information about a specific migration."""
        status_file = os.path.join(project_path, 'migration_logs', f"{migration_id}_status.json")
        log_content = ProgressTracker.get_migration_log(project_path, migration_id)
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return {
                'status': status,
                'log': log_content
            }
        except FileNotFoundError:
            return None 