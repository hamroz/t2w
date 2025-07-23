import requests
import json
import base64
from urllib.parse import urljoin
import time

class WordPressAPI:
    """WordPress REST API client for migrating content."""
    
    def __init__(self, site_url, username, password, timeout=30):
        """Initialize the WordPress API client."""
        self.site_url = site_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set up authentication headers
        credentials = f"{username}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        self.session.headers.update({
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json'
        })
    
    def test_connection(self):
        """Test the connection to WordPress and validate credentials."""
        try:
            response = self._make_request('GET', '/wp-json/wp/v2/users/me')
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'success': True,
                    'message': f"Connected successfully as {user_data.get('name', 'Unknown')}",
                    'user': user_data
                }
            else:
                return {
                    'success': False,
                    'message': f"Authentication failed: {response.status_code}",
                    'error': response.text
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'message': f"Connection failed: {str(e)}",
                'error': str(e)
            }
    
    def create_page(self, title, slug, content_blocks, parent_id=None, status='publish', template=''):
        """Create a WordPress page with Gutenberg blocks."""
        try:
            # Convert content blocks to Gutenberg format
            gutenberg_content = self._convert_to_gutenberg(content_blocks)
            
            page_data = {
                'title': title,
                'slug': slug,
                'content': gutenberg_content,
                'status': status,
                'type': 'page'
            }
            
            # Set parent if specified (for hierarchy)
            if parent_id:
                page_data['parent'] = parent_id

            # Set page template if specified
            if template:
                page_data['template'] = template
            
            response = self._make_request('POST', '/wp-json/wp/v2/pages', data=page_data)
            
            if response.status_code == 201:
                page_info = response.json()
                return {
                    'success': True,
                    'message': f"Page '{title}' created successfully",
                    'page_id': page_info['id'],
                    'url': page_info['link'],
                    'data': page_info
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return {
                    'success': False,
                    'message': f"Failed to create page '{title}': {response.status_code}",
                    'error': error_data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Error creating page '{title}': {str(e)}",
                'error': str(e)
            }
    
    def get_page_by_slug(self, slug):
        """Check if a page with the given slug already exists."""
        try:
            response = self._make_request('GET', f'/wp-json/wp/v2/pages?slug={slug}')
            if response.status_code == 200:
                pages = response.json()
                return pages[0] if pages else None
            return None
        except Exception:
            return None
    
    def create_menu(self, menu_name, menu_items):
        """Create a WordPress menu with hierarchical structure."""
        try:
            # First, create the menu
            menu_data = {
                'name': menu_name,
                'description': f'Migrated menu: {menu_name}'
            }
            
            # Note: WordPress REST API doesn't directly support menu creation
            # This is a simplified version - in reality, you might need to use
            # wp-api-menus plugin or custom endpoints
            
            return {
                'success': True,
                'message': f"Menu structure prepared: {menu_name}",
                'menu_items': menu_items
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Error creating menu '{menu_name}': {str(e)}",
                'error': str(e)
            }
    
    def _convert_to_gutenberg(self, content_blocks):
        """Convert parsed content blocks to Gutenberg block format wrapped in Group -> Column -> Narrow."""
        inner_content = ""
        
        for block in content_blocks:
            if block['type'] == 'heading':
                # Create heading block
                inner_content += f"""
<!-- wp:heading -->
<h2 class="wp-block-heading">{self._escape_html(block['text'])}</h2>
<!-- /wp:heading -->

"""
            elif block['type'] == 'paragraph':
                # Create paragraph block
                inner_content += f"""
<!-- wp:paragraph -->
<p>{self._escape_html(block['text'])}</p>
<!-- /wp:paragraph -->

"""
            elif block['type'] == 'button':
                # Create button block (skip if no text)
                if block.get('text'):
                    href = block.get('href', '#')
                    inner_content += f"""
<!-- wp:buttons -->
<div class="wp-block-buttons">
<!-- wp:button -->
<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="{self._escape_html(href)}">{self._escape_html(block['text'])}</a></div>
<!-- /wp:button -->
</div>
<!-- /wp:buttons -->

"""
            # Skip image blocks as requested
            
        # Wrap all content in Group -> Columns -> Column (with Narrow style)
        return f"""
<!-- wp:group {{"layout":{{"type":"constrained"}}}} -->
<div class="wp-block-group">
<!-- wp:columns -->
<div class="wp-block-columns">
<!-- wp:column {{"className":"is-style-narrow is-style-fs-column-narrow"}} -->
<div class="wp-block-column is-style-narrow is-style-fs-column-narrow">
{inner_content.rstrip()}
</div>
<!-- /wp:column -->
</div>
<!-- /wp:columns -->
</div>
<!-- /wp:group -->
"""
    
    def _escape_html(self, text):
        """Escape HTML characters in text."""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))
    
    def _make_request(self, method, endpoint, data=None):
        """Make a request to the WordPress REST API."""
        url = urljoin(self.site_url, endpoint)
        
        if method.upper() == 'GET':
            return self.session.get(url, timeout=self.timeout)
        elif method.upper() == 'POST':
            return self.session.post(url, json=data, timeout=self.timeout)
        elif method.upper() == 'PUT':
            return self.session.put(url, json=data, timeout=self.timeout)
        elif method.upper() == 'DELETE':
            return self.session.delete(url, timeout=self.timeout)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
    
    def get_site_info(self):
        """Get basic site information."""
        try:
            response = self._make_request('GET', '/wp-json')
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None 

    def upload_image(self, image_path, title=None, alt_text=None):
        """Upload an image to WordPress media library."""
        try:
            import os
            
            if not os.path.exists(image_path):
                return {
                    'success': False,
                    'message': f"Image file not found: {image_path}",
                    'error': 'File not found'
                }
            
            # Get file info
            filename = os.path.basename(image_path)
            if not title:
                title = os.path.splitext(filename)[0]
            
            # Prepare multipart form data
            with open(image_path, 'rb') as img_file:
                files = {
                    'file': (filename, img_file, self._get_mime_type(image_path))
                }
                
                # Prepare headers (remove Content-Type to let requests set it for multipart)
                headers = {
                    'Authorization': self.session.headers['Authorization']
                }
                
                # Prepare media data
                data = {
                    'title': title,
                    'alt_text': alt_text or '',
                    'status': 'publish'
                }
                
                response = requests.post(
                    f"{self.site_url}/wp-json/wp/v2/media",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=self.timeout
                )
            
            if response.status_code == 201:
                media_info = response.json()
                return {
                    'success': True,
                    'message': f"Image '{filename}' uploaded successfully",
                    'media_id': media_info['id'],
                    'url': media_info['source_url'],
                    'data': media_info
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return {
                    'success': False,
                    'message': f"Failed to upload image '{filename}': {response.status_code}",
                    'error': error_data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Error uploading image '{filename}': {str(e)}",
                'error': str(e)
            }
    
    def set_featured_image(self, page_id, media_id):
        """Set a featured image for a page."""
        try:
            page_data = {
                'featured_media': media_id
            }
            
            response = self._make_request('POST', f'/wp-json/wp/v2/pages/{page_id}', data=page_data)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': f"Featured image set for page ID {page_id}",
                    'page_id': page_id,
                    'media_id': media_id
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return {
                    'success': False,
                    'message': f"Failed to set featured image for page {page_id}: {response.status_code}",
                    'error': error_data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Error setting featured image for page {page_id}: {str(e)}",
                'error': str(e)
            }
    
    def get_pages_list(self):
        """Get a list of all pages from WordPress."""
        try:
            pages = []
            page = 1
            per_page = 100
            
            while True:
                response = self._make_request('GET', f'/wp-json/wp/v2/pages?per_page={per_page}&page={page}')
                if response.status_code == 200:
                    batch_pages = response.json()
                    if not batch_pages:
                        break
                    pages.extend(batch_pages)
                    page += 1
                else:
                    break
            
            return {
                'success': True,
                'pages': pages,
                'count': len(pages)
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Error fetching pages: {str(e)}",
                'error': str(e)
            }
    
    def _get_mime_type(self, file_path):
        """Get MIME type for a file."""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or 'application/octet-stream' 