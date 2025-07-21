import requests
import json
from urllib.parse import urljoin

class WordPressMenuCreator:
    """Creates WordPress menus using native WordPress 6.8+ REST API endpoints."""
    
    def __init__(self, wp_api):
        """Initialize with WordPress API client."""
        self.wp_api = wp_api
    
    def create_menu_with_native_api(self, menu_items, page_mapping, menu_name="Main Navigation"):
        """Create menu using native WordPress REST API endpoints (WordPress 6.8+)."""
        try:
            # Step 1: Create the menu using /wp/v2/menus
            menu_result = self._create_menu(menu_name)
            if not menu_result['success']:
                return menu_result
            
            menu_id = menu_result['menu_id']
            
            # Step 2: Add menu items with hierarchy using /wp/v2/menu-items
            items_result = self._add_menu_items_hierarchical(menu_id, menu_items, page_mapping)
            if not items_result['success']:
                return items_result
            
            # Step 3: Assign menu to 'primary' theme location
            assign_result = self._assign_menu_to_primary_location(menu_id)
            if not assign_result['success']:
                return assign_result
            
            return {
                'success': True,
                'message': f"Menu '{menu_name}' created successfully with {items_result['items_added']} items and assigned to primary location",
                'menu_id': menu_id,
                'items_added': items_result['items_added']
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Error creating menu: {str(e)}",
                'error': str(e)
            }
    
    def _create_menu(self, menu_name):
        """Create a new navigation menu using WordPress native REST API."""
        try:
            # Delete existing menu with the same name first
            existing_menus = self._get_existing_menus()
            for menu in existing_menus:
                if menu.get('name') == menu_name:
                    self._delete_menu(menu['id'])
            
            # Create new menu
            menu_data = {
                'name': menu_name,
                'description': f'Migrated navigation menu: {menu_name}',
                'locations': ['primary']  # Assign to primary location
            }
            
            response = self.wp_api._make_request('POST', '/wp-json/wp/v2/menus', data=menu_data)
            
            if response.status_code == 201:
                menu_info = response.json()
                return {
                    'success': True,
                    'menu_id': menu_info['id'],
                    'message': f"Menu '{menu_name}' created"
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return {
                    'success': False,
                    'message': f"Failed to create menu: {response.status_code}",
                    'error': error_data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Failed to create menu: {str(e)}",
                'error': str(e)
            }
    
    def _get_existing_menus(self):
        """Get all existing menus."""
        try:
            response = self.wp_api._make_request('GET', '/wp-json/wp/v2/menus')
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []
    
    def _delete_menu(self, menu_id):
        """Delete an existing menu."""
        try:
            response = self.wp_api._make_request('DELETE', f'/wp-json/wp/v2/menus/{menu_id}')
            return response.status_code == 200
        except Exception:
            return False
    
    def _add_menu_items_hierarchical(self, menu_id, menu_items, page_mapping):
        """Add menu items to the menu with proper hierarchy."""
        items_added = 0
        item_id_mapping = {}  # Maps order to WordPress menu item ID for parent relationships
        
        try:
            # Process items in order to maintain hierarchy
            flattened_items = self._flatten_menu_items(menu_items)
            
            for item_data in flattened_items:
                result = self._create_menu_item(menu_id, item_data, page_mapping, item_id_mapping)
                if result['success']:
                    items_added += 1
                    item_id_mapping[item_data['order']] = result['menu_item_id']
            
            return {
                'success': True,
                'items_added': items_added
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Error adding menu items: {str(e)}",
                'items_added': items_added
            }
    
    def _flatten_menu_items(self, menu_items, parent_order=None, order_counter=None):
        """Flatten hierarchical menu items while preserving parent relationships."""
        if order_counter is None:
            order_counter = [0]  # Use list to make it mutable
        
        flattened = []
        
        for item in menu_items:
            order_counter[0] += 1
            current_order = order_counter[0]
            
            # Map from parser format to menu creator format
            # Parser uses: 'title' and 'slug' fields
            # Menu creator expects: 'text' and 'href' fields
            title = item.get('title', item.get('text', 'Untitled'))
            url = item.get('slug', item.get('href', '#'))
            
            flattened_item = {
                'title': title,
                'url': url,
                'order': current_order,
                'parent_order': parent_order
            }
            
            flattened.append(flattened_item)
            
            # Process children recursively
            # Parser uses 'submenu' field, menu creator expects 'children'
            children = item.get('submenu', item.get('children', []))
            if children:
                child_items = self._flatten_menu_items(
                    children, 
                    current_order, 
                    order_counter
                )
                flattened.extend(child_items)
        
        return flattened
    
    def _create_menu_item(self, menu_id, item_data, page_mapping, item_id_mapping):
        """Create a single menu item."""
        try:
            menu_item_data = {
                'title': item_data['title'],
                'menu_order': item_data['order'],
                'menus': menu_id,
                'status': 'publish'
            }
            
            # Handle parent relationships
            if item_data['parent_order'] and item_data['parent_order'] in item_id_mapping:
                menu_item_data['parent'] = item_id_mapping[item_data['parent_order']]
            
            # Determine item type and object
            href = item_data['url']
            if href in page_mapping:
                # Link to WordPress page
                menu_item_data.update({
                    'type': 'post_type',
                    'object': 'page',
                    'object_id': page_mapping[href]
                })
            else:
                # Custom URL
                menu_item_data.update({
                    'type': 'custom',
                    'url': href
                })
            
            response = self.wp_api._make_request('POST', '/wp-json/wp/v2/menu-items', data=menu_item_data)
            
            if response.status_code == 201:
                menu_item_info = response.json()
                return {
                    'success': True,
                    'menu_item_id': menu_item_info['id'],
                    'message': f"Menu item '{item_data['title']}' created"
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                return {
                    'success': False,
                    'message': f"Failed to create menu item '{item_data['title']}': {response.status_code}",
                    'error': error_data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Error creating menu item '{item_data['title']}': {str(e)}",
                'error': str(e)
            }
    
    def _assign_menu_to_primary_location(self, menu_id):
        """Assign menu to primary theme location."""
        try:
            # Update the menu to assign it to primary location
            menu_data = {
                'locations': ['primary']
            }
            
            response = self.wp_api._make_request('PUT', f'/wp-json/wp/v2/menus/{menu_id}', data=menu_data)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': "Menu assigned to primary location"
                }
            else:
                return {
                    'success': False,
                    'message': f"Failed to assign menu to primary location: {response.status_code}"
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"Error assigning menu to location: {str(e)}",
                'error': str(e)
            }


# Legacy class for backwards compatibility
class WordPressMenuManager(WordPressMenuCreator):
    """Legacy wrapper for WordPressMenuCreator."""
    
    def __init__(self, wp_api):
        super().__init__(wp_api)
        self.created_pages = {}
    
    def set_page_mapping(self, page_mapping):
        """Set the mapping of slugs to WordPress page IDs."""
        self.created_pages = page_mapping
    
    def create_primary_menu(self, menu_items, menu_name="Main Navigation"):
        """Create primary menu using the new native API method."""
        return self.create_menu_with_native_api(menu_items, self.created_pages, menu_name) 