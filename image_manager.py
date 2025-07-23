import os
import json
import re
from wordpress_api import WordPressAPI

class ImageManager:
    """Manages image uploads and assignments for WordPress migration."""
    
    def __init__(self, project_path, wp_site_url, wp_username, wp_password):
        """Initialize the image manager."""
        self.project_path = project_path
        self.wp_api = WordPressAPI(wp_site_url, wp_username, wp_password)
        self.images_dir = os.path.join(project_path, 'images')
        self.assignments_file = os.path.join(project_path, 'image_assignments.json')
        
        # Create images directory if it doesn't exist
        os.makedirs(self.images_dir, exist_ok=True)
    
    def get_local_images(self):
        """Get all images from the project's images directory."""
        if not os.path.exists(self.images_dir):
            return []
        
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}
        images = []
        
        for filename in os.listdir(self.images_dir):
            file_path = os.path.join(self.images_dir, filename)
            if os.path.isfile(file_path):
                _, ext = os.path.splitext(filename.lower())
                if ext in image_extensions:
                    file_size = os.path.getsize(file_path)
                    images.append({
                        'filename': filename,
                        'path': file_path,
                        'size': file_size,
                        'size_human': self._human_size(file_size)
                    })
        
        return sorted(images, key=lambda x: x['filename'])
    
    def get_wordpress_pages(self):
        """Get all pages from WordPress."""
        result = self.wp_api.get_pages_list()
        if result['success']:
            return result['pages']
        return []
    
    def upload_images_bulk(self, image_paths, progress_callback=None):
        """Upload multiple images to WordPress media library."""
        results = []
        total = len(image_paths)
        
        for i, image_path in enumerate(image_paths):
            if progress_callback:
                progress_callback(i, total, f"Uploading {os.path.basename(image_path)}...")
            
            filename = os.path.basename(image_path)
            title = self._clean_filename_for_title(filename)
            
            result = self.wp_api.upload_image(image_path, title=title)
            results.append({
                'filename': filename,
                'path': image_path,
                'result': result
            })
        
        if progress_callback:
            progress_callback(total, total, "Upload complete!")
        
        return results
    
    def save_assignments(self, assignments):
        """Save image-page assignments to file."""
        try:
            with open(self.assignments_file, 'w', encoding='utf-8') as f:
                json.dump(assignments, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving assignments: {e}")
            return False
    
    def load_assignments(self):
        """Load saved image-page assignments."""
        try:
            if os.path.exists(self.assignments_file):
                with open(self.assignments_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading assignments: {e}")
        return {}
    
    def assign_featured_images(self, assignments, progress_callback=None):
        """Assign featured images to pages based on assignments."""
        results = []
        total = len(assignments)
        
        for i, (page_id, media_id) in enumerate(assignments.items()):
            if progress_callback:
                progress_callback(i, total, f"Assigning image to page {page_id}...")
            
            result = self.wp_api.set_featured_image(int(page_id), int(media_id))
            results.append({
                'page_id': page_id,
                'media_id': media_id,
                'result': result
            })
        
        if progress_callback:
            progress_callback(total, total, "Assignment complete!")
        
        return results
    
    def _clean_filename_for_title(self, filename):
        """Clean filename to create a nice title."""
        name = os.path.splitext(filename)[0]
        # Replace underscores and hyphens with spaces
        name = re.sub(r'[-_]', ' ', name)
        # Remove extra spaces
        name = ' '.join(name.split())
        # Title case
        return name.title()
    
    def _human_size(self, size_bytes):
        """Convert bytes to human readable format."""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024.0 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"
    
    def get_uploaded_media(self, uploaded_results):
        """Extract media info from upload results."""
        media_items = []
        for upload in uploaded_results:
            if upload['result']['success']:
                media_items.append({
                    'filename': upload['filename'],
                    'media_id': upload['result']['media_id'],
                    'url': upload['result']['url'],
                    'title': upload['result']['data']['title']['rendered']
                })
        return media_items 