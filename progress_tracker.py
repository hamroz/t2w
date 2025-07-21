import json
import os
import time
from datetime import datetime
from threading import Lock

class ProgressTracker:
    """Tracks migration progress and logs operations for real-time updates."""
    
    def __init__(self, project_path, migration_id=None):
        """Initialize the progress tracker."""
        self.project_path = project_path
        self.migration_id = migration_id or f"migration_{int(time.time())}"
        self.logs_dir = os.path.join(project_path, 'migration_logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.logs_dir, f"{self.migration_id}.log")
        self.status_file = os.path.join(self.logs_dir, f"{self.migration_id}_status.json")
        
        self.lock = Lock()
        self.status = {
            'migration_id': self.migration_id,
            'started_at': datetime.now().isoformat(),
            'completed_at': None,
            'status': 'initializing',  # initializing, running, completed, failed
            'total_pages': 0,
            'processed_pages': 0,
            'successful_pages': 0,
            'failed_pages': 0,
            'current_operation': '',
            'percentage': 0,
            'errors': [],
            'warnings': []
        }
        
        self._save_status()
        self._log_message("Migration initialized", "INFO")
    
    def start_migration(self, total_pages):
        """Start the migration process."""
        with self.lock:
            self.status.update({
                'status': 'running',
                'total_pages': total_pages,
                'current_operation': 'Starting migration process'
            })
            self._save_status()
            self._log_message(f"Starting migration with {total_pages} pages", "INFO")
    
    def log_operation(self, message, level="INFO", operation_type="general"):
        """Log a migration operation."""
        with self.lock:
            self.status['current_operation'] = message
            self._save_status()
            self._log_message(message, level, operation_type)
    
    def log_page_success(self, page_title, page_url, wordpress_url):
        """Log successful page creation."""
        with self.lock:
            self.status['processed_pages'] += 1
            self.status['successful_pages'] += 1
            self.status['percentage'] = int((self.status['processed_pages'] / self.status['total_pages']) * 100)
            self.status['current_operation'] = f"✓ Created page: {page_title}"
            self._save_status()
            
            message = f"✓ Created page: '{page_title}' ({page_url}) -> {wordpress_url}"
            self._log_message(message, "SUCCESS", "page_creation")
    
    def log_page_failure(self, page_title, page_url, error):
        """Log failed page creation."""
        with self.lock:
            self.status['processed_pages'] += 1
            self.status['failed_pages'] += 1
            self.status['percentage'] = int((self.status['processed_pages'] / self.status['total_pages']) * 100)
            self.status['current_operation'] = f"✗ Failed to create page: {page_title}"
            
            error_entry = {
                'page_title': page_title,
                'page_url': page_url,
                'error': str(error),
                'timestamp': datetime.now().isoformat()
            }
            self.status['errors'].append(error_entry)
            self._save_status()
            
            message = f"✗ Failed to create page: '{page_title}' ({page_url}) - Error: {error}"
            self._log_message(message, "ERROR", "page_creation")
    
    def log_page_skipped(self, page_title, page_url, reason):
        """Log skipped page (e.g., already exists)."""
        with self.lock:
            self.status['processed_pages'] += 1
            self.status['percentage'] = int((self.status['processed_pages'] / self.status['total_pages']) * 100)
            self.status['current_operation'] = f"⚠ Skipped page: {page_title}"
            
            warning_entry = {
                'page_title': page_title,
                'page_url': page_url,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }
            self.status['warnings'].append(warning_entry)
            self._save_status()
            
            message = f"⚠ Skipped page: '{page_title}' ({page_url}) - Reason: {reason}"
            self._log_message(message, "WARNING", "page_creation")
    
    def complete_migration(self, success=True):
        """Complete the migration process."""
        with self.lock:
            self.status.update({
                'status': 'completed' if success else 'failed',
                'completed_at': datetime.now().isoformat(),
                'percentage': 100 if success else self.status['percentage'],
                'current_operation': '🎉 Migration completed!' if success else '❌ Migration failed'
            })
            self._save_status()
            
            if success:
                success_rate = (self.status['successful_pages'] / self.status['total_pages']) * 100
                message = f"🎉 Migration completed! {self.status['successful_pages']}/{self.status['total_pages']} pages successful ({success_rate:.1f}%)"
            else:
                message = "❌ Migration failed"
            
            self._log_message(message, "INFO", "migration_complete")
    
    def get_status(self):
        """Get current migration status."""
        with self.lock:
            return self.status.copy()
    
    def get_recent_logs(self, limit=50):
        """Get recent log entries."""
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return lines[-limit:] if len(lines) > limit else lines
        except FileNotFoundError:
            return []
    
    def _save_status(self):
        """Save current status to file."""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(self.status, f, indent=2)
        except Exception as e:
            # Fallback logging if status file can't be written
            print(f"Error saving status: {e}")
    
    def _log_message(self, message, level="INFO", operation_type="general"):
        """Write a message to the log file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {level:7} | {message}\n"
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            # Fallback to console if file logging fails
            print(f"Logging error: {e}")
            print(log_entry.strip())
    
    @classmethod
    def get_migration_history(cls, project_path):
        """Get list of all previous migrations for a project."""
        logs_dir = os.path.join(project_path, 'migration_logs')
        if not os.path.exists(logs_dir):
            return []
        
        migrations = []
        for filename in os.listdir(logs_dir):
            if filename.endswith('_status.json'):
                try:
                    with open(os.path.join(logs_dir, filename), 'r', encoding='utf-8') as f:
                        status = json.load(f)
                        migrations.append(status)
                except Exception:
                    continue
        
        # Sort by started_at timestamp, newest first
        migrations.sort(key=lambda x: x.get('started_at', ''), reverse=True)
        return migrations
    
    @classmethod
    def get_migration_log(cls, project_path, migration_id):
        """Get the full log for a specific migration."""
        log_file = os.path.join(project_path, 'migration_logs', f"{migration_id}.log")
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "Log file not found." 